# Vous testez l'outil — merci

Ce qui compte le plus, à ce stade, c'est de savoir comment il se comporte sur de **vrais**
enregistrements de réunion. Les tests automatiques couvrent le traitement du signal ; ils ne
disent rien de ce que ça donne sur cinq personnes autour d'une table.

## Installer

1. [Python 3.9 ou plus récent](https://www.python.org/downloads/) — sous Windows, cocher
   « Add python.exe to PATH ».
2. Télécharger le dépôt (**Code → Download ZIP**), décompresser.
3. Double-cliquer sur `Demarrer_Mac_Linux.command` ou `Demarrer_Windows.bat`.
4. Dans la page, panneau **Installation** à droite : bouton *Installer* du moteur de
   transcription, puis *Télécharger* le modèle.

Aucune commande à taper. Si vous en tapez une, c'est un bug — signalez-le.

## D'abord : la vérification automatique

Panneau **Installation**, ligne *Vérifier sur cette machine*, bouton **Lancer**. En une minute
vous obtenez le taux d'erreur, la vitesse réelle sur votre machine et le nombre de mots
inventés sur du silence.

**Collez ces trois chiffres dans votre retour** : ils rendent tous les retours comparables
entre machines, et ils disent tout de suite si un mauvais résultat vient du moteur ou de
l'enregistrement.

## Le parcours à essayer

1. **Un enregistrement réel**, si possible pas le plus propre de votre collection.
2. **L'aperçu de 20 secondes** avant de traiter : basculez entre *Avant* et *Après*. Les deux
   extraits sont au même volume, vous comparez donc la qualité et non le niveau.
3. **Traitez**, puis ouvrez le compte rendu Word.
4. Si vous avez un enregistrement long (une heure ou plus), lancez-le et dites-nous combien de
   temps ça a pris et sur quelle machine.

## Les questions auxquelles on cherche des réponses

**Sur l'audio**

- La voix la plus lointaine est-elle devenue intelligible ?
- Entendez-vous des artefacts : voix « métallique », qui ondule, débuts de mots coupés ?
- Un préréglage donne-t-il un meilleur résultat que celui par défaut sur votre matériel ?

**Sur la transcription**

- Quel modèle avez-vous utilisé, sur quelle machine, et combien de temps pour quelle durée ?
- Le taux d'erreur vous paraît-il acceptable pour relire, ou faut-il tout reprendre ?
- Le champ *Vocabulaire de la réunion* a-t-il amélioré les noms propres ?
- Whisper a-t-il inventé des phrases dans les silences ?

**Sur les intervenants**

- Combien de personnes, et combien l'outil en a-t-il trouvées ?
- Le fait d'indiquer le nombre à l'avance a-t-il changé quelque chose ?
- Les tours de parole sont-ils coupés au bon endroit ?

**Sur le relevé automatique**

- Combien de décisions et d'actions réellement pertinentes, sur combien de repérées ?
- Qu'est-ce qui a été manqué et qui aurait dû être repéré ? (la formulation exacte nous
  intéresse : c'est ce qui permet d'enrichir la détection)

## Faire un retour

Ouvrez une *issue* sur GitHub — les modèles proposés posent déjà les bonnes questions.

Précisez toujours : système d'exploitation, machine (processeur, carte graphique éventuelle),
durée et provenance de l'enregistrement, modèle utilisé.

**N'envoyez jamais d'audio ni de verbatim confidentiel dans une issue.** Le contenu de vos
réunions ne doit pas se retrouver sur GitHub. Décrivez le problème, ou fabriquez un extrait
neutre — `python tests/make_dialogue.py` en génère un.

En cas d'erreur, le contenu du panneau **Installation** et le message affiché dans la barre de
progression sont les deux informations les plus utiles.
