# Hypothesis Lab V1 tools

```text
EXPLORATORY
UNVALIDATED
NO_PROMOTION
NO_BET
```

`catalogue-source-v1.json` gèle les 8 familles, 112 questions structurées et 9 contrôles sans
résultat sportif. `raw-candidates-v1.json` persiste les 336 formulations brutes sans ID
canonique ; `portfolio-strata-v1.json` gèle les 25 slots et leurs définitions opérationnelles.
`build_catalogue.py` cluster d'abord le registre brut avec `ESTIMAND_SIGNATURE_V2`, assigne
ensuite les identités, construit
les six rapports, les valide contre `hypothesis-lab-artifact-schema-v1.json`, puis les écrit
avec `--write` ou compare leurs octets avec `--check`.

Le générateur est strictement local et déterministe. Il n'accède à aucun provider, aucune
base de production, aucun objet R2 et n'exécute aucun backtest. La validation est fail-closed
sur les triples de-vig, les rôles prédicteur/target/label, les AST sémantiques des seules
collisions, les clusters, les strates, les estimateurs, les plans de puissance non exécutés,
les références inter-rapports et les hashes des trois sources gelées.

Le simulateur de puissance design-only est callable mais n'est jamais lancé par `--write` ou
`--check`. Il génère uniquement des fixtures synthétiques depuis la matrice et le contraste
gelés, partage les tirages latents entre branches de-vig, ajuste le modèle linéaire déclaré et
applique la covariance sandwich, les deux corrections BH et la borne de Wilson.

```powershell
$pythonExe = 'python'
& $pythonExe tools/hypothesis-lab/build_catalogue.py --write
& $pythonExe tools/hypothesis-lab/build_catalogue.py --check
```

L'option `--output-dir` sert uniquement aux fixtures temporaires de test. Un snapshot réel
doit rester `NOT_YET_MATERIALIZED` jusqu'à ce que son identité native et son SHA-256 soient
gelés dans un manifeste séparé.
