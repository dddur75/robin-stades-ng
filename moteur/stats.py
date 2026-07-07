"""Statistiques honnetes : IC de Wilson, tests binomiaux, correction FDR (Benjamini-Hochberg)."""
import numpy as np


def wilson_ci(hits: int, n: int, z: float = 1.96):
    """Intervalle de confiance de Wilson pour une proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    demi = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - demi), min(1.0, centre + demi))


def z_vs_probas(hits: int, probas):
    """Z-score des succes observes vs somme de Bernoulli aux probas donnees.
    Etage 2 : probas justes issues de la cloture de-viggee (variables par match).
    Etage 1 : proba de base repetee."""
    probas = np.asarray(probas, dtype=float)
    mu = probas.sum()
    var = (probas * (1 - probas)).sum()
    if var <= 0:
        return 0.0
    return (hits - mu) / np.sqrt(var)


def p_value_bilaterale(z: float) -> float:
    from math import erf, sqrt
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))


def benjamini_hochberg(pvals, q: float = 0.10):
    """True si le test passe la FDR au niveau q."""
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    if n == 0:
        return np.array([], dtype=bool)
    ordre = np.argsort(pvals)
    seuils = q * (np.arange(1, n + 1)) / n
    passe_tri = pvals[ordre] <= seuils
    k = np.max(np.where(passe_tri)[0]) + 1 if passe_tri.any() else 0
    resultat = np.zeros(n, dtype=bool)
    resultat[ordre[:k]] = True
    return resultat


def roi_flat(gains):
    """ROI a mise plate 1u. gains = retours nets par pari (cote-1 si gagne, -1 sinon)."""
    g = np.asarray(gains, dtype=float)
    if len(g) == 0:
        return 0.0, (0.0, 0.0)
    roi = g.mean()
    se = g.std(ddof=1) / np.sqrt(len(g)) if len(g) > 1 else 0.0
    return roi, (roi - 1.96 * se, roi + 1.96 * se)
