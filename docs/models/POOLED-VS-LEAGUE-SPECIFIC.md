# Pooled vs league-specific

Le protocole fixe un multinomial régularisé, une standardisation par ligue,
300 itérations, learning rate 0,08, régularisation 0,01 et seed 1707.

Sur 2 136 fixtures exactement appariées :

- pooled : Log Loss 0,99584 ;
- league-specific : 0,99830 ;
- delta league-specific moins pooled : +0,00246 ;
- CI 95 % : [-0,00251 ; +0,00753] ;
- P(league-specific meilleur) : 0,166.

Le résultat est `INCONCLUSIVE`. Le pooled n’est pas promu et aucun retuning
n’est autorisé après lecture.
