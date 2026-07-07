"""De-vigging des cotes : Shin (defaut) et proportionnel.
Juge de verite = probabilites justes extraites de la cloture Pinnacle."""
import numpy as np


def devig_proportionnel(cotes):
    imp = np.array([1.0 / c for c in cotes], dtype=float)
    return imp / imp.sum()


def devig_shin(cotes, iterations: int = 100):
    """Methode de Shin : retire la marge en modelisant la part d'insiders.
    Resolution iterative de z ; retombe sur le proportionnel en cas degenere."""
    imp = np.array([1.0 / c for c in cotes], dtype=float)
    s = imp.sum()
    if s <= 1.0:
        return imp / s
    n = len(imp)
    if n == 2:
        return devig_proportionnel(cotes)  # 2 issues : Shin ~ proportionnel
    z = 0.0
    for _ in range(iterations):
        racine = np.sqrt(z**2 + 4 * (1 - z) * (imp**2) / s)
        z_next = (racine.sum() - 2) / (n - 2)
        if abs(z_next - z) < 1e-12:
            z = z_next
            break
        z = max(0.0, min(0.99, z_next))
    racine = np.sqrt(z**2 + 4 * (1 - z) * (imp**2) / s)
    p = (racine - z) / (2 * (1 - z))
    p = np.clip(p, 1e-9, 1.0)
    return p / p.sum()


def probas_justes(cotes, methode: str = "shin"):
    cotes = list(cotes)
    if any(c is None or not np.isfinite(c) or c <= 1.0 for c in cotes):
        return None
    if methode == "shin":
        return devig_shin(cotes)
    return devig_proportionnel(cotes)
