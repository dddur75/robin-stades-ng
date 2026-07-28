"""Création de moteurs et sessions SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(ValueError):
    """Erreur de configuration sûre, sans reprise de la valeur secrète."""


def normalize_database_url(database_url: str | None) -> str:
    """Normaliser une URL utilisateur vers le pilote réellement installé."""

    if database_url is None or not database_url.strip():
        raise DatabaseConfigurationError("URL de base de données absente")
    candidate = database_url.strip()
    if candidate.startswith("postgresql://"):
        candidate = "postgresql+psycopg://" + candidate.removeprefix(
            "postgresql://"
        )
    try:
        parsed = make_url(candidate)
    except ArgumentError:
        raise DatabaseConfigurationError(
            "URL de base de données invalide"
        ) from None
    backend = parsed.get_backend_name()
    if backend == "postgresql" and parsed.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError(
            "pilote PostgreSQL incompatible ; Psycopg 3 est requis"
        )
    if backend not in {"postgresql", "sqlite"}:
        raise DatabaseConfigurationError(
            "type de base de données non pris en charge"
        )
    return parsed.render_as_string(hide_password=False)


def database_url_object(database_url: str | None) -> URL:
    """Retourner un objet URL dont la représentation masque le mot de passe."""

    return make_url(normalize_database_url(database_url))


def alembic_database_url(database_url: str | None) -> str:
    """Échapper les pourcentages pour l'interpolation ConfigParser d'Alembic."""

    return normalize_database_url(database_url).replace("%", "%%")


def build_engine(database_url: str, *, echo: bool = False) -> Engine:
    url = database_url_object(database_url)
    connect_args: dict[str, object] = {}
    if url.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
    elif url.get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = 10
    if url.get_backend_name() == "postgresql":
        engine = create_engine(
            url,
            echo=echo,
            future=True,
            connect_args=connect_args,
            pool_pre_ping=True,
            pool_recycle=240,
        )
    else:
        engine = create_engine(
            url,
            echo=echo,
            future=True,
            connect_args=connect_args,
        )
    if url.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        yield session
