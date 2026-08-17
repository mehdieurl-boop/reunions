# Manuel d'utilisation

Prend un enregistrement de réunion (export Zoom, dictaphone, visio) et en sort, en un
passage : un audio nettoyé, un verbatim horodaté avec les intervenants séparés, un compte
rendu Word et un fichier de données réutilisable.

Tout se passe sur votre machine. Aucun fichier n'est envoyé sur Internet, y compris pour
la transcription.

---

## Démarrage

| Système | Quoi faire |
|---|---|
| macOS / Linux | double-cliquer sur `Demarrer_Mac_Linux.command` |
| Windows | double-cliquer sur `Demarrer_Windows.bat` |

C'est tout. Au premier lancement l'installation prend une à deux minutes, puis le navigateur
s'ouvre sur `http://127.0.0.1:7862`. **Tout le reste se fait depuis la page** : ajouter la
transcription, télécharger les modèles, choisir les dossiers, lancer le traitement
automatique. Aucune commande à taper.

**Prérequis** : Python 3.9 ou plus récent ([python.org](https://www.python.org/downloads/) —
sous Windows, cocher « Add python.exe to PATH »). `ffmpeg` est installé automatiquement via
le paquet `imageio-ffmpeg` ; si vous l'avez déjà (`brew install ffmpeg`,
`winget install Gyan.FFmpeg`), il sera utilisé en priorité.

---

## Comment s'en servir

1. **Déposez** vos fichiers dans la zone de glisser-déposer. Pour un fichier volumineux,
   collez plutôt son chemin complet : il sera lu sur place, sans recopie.
2. **Choisissez un préréglage**, puis ajustez si besoin.
3. **Écoutez l'aperçu de 20 secondes** et basculez entre *Avant* et *Après*. Les deux
   extraits sont calés au même volume : vous jugez la qualité, pas le niveau. C'est la
   bonne manière de régler les curseurs sans traiter une heure d'audio à chaque essai.
4. **Nettoyez** : les fichiers arrivent dans `Reunions_nettoyees` (dans votre dossier
   personnel).

### Préréglages

| Préréglage | Pour quel enregistrement |
|---|---|
| **Zoom standard** | cas courant, micros corrects, un peu de souffle |
| **Micro éloigné** | un intervenant loin du micro, voix noyée dans la pièce |
| **Bon micro** | casque ou micro USB : on corrige peu, on garde le naturel |
| **Salle bruyante** | présentiel capté par un seul micro, clim, brouhaha |

### Les réglages

| Réglage | Effet |
|---|---|
| **Débruitage** | retire le bruit stable : souffle, ventilation, ronronnement d'ordinateur |
| **Douceur des aigus** | calme la brillance et les sifflantes (désesseur) |
| **Compression** | rapproche les voix fortes et les voix lointaines |
| **Intelligibilité** | léger relief à 2,8 kHz : articulation plus nette |
| **Coupe-grave** | enlève les grondements de table, de pas, de climatisation |
| **Atténuer le fond** | expandeur : baisse le fond entre les prises de parole |
| **Ronflement secteur** | détecte et supprime le 50 Hz (Europe) ou 60 Hz et ses harmoniques |
| **Conserver la stéréo** | décoché par défaut : le mono est deux fois plus rapide et n'enlève rien à la parole |

### Les deux exports

- **Version écoute** — MP3 (ou WAV / FLAC), −16 LUFS, crête à −1 dBFS. Pour réécouter.
- **Version transcription** — WAV mono 16 kHz, −20 LUFS. C'est exactement ce qu'attendent
  Whisper et la plupart des moteurs, qui rééchantillonnent de toute façon en 16 kHz mono.

Deux options utiles pour la transcription :

- **Raccourcir les longs silences** — réduit la durée à transcrire (et donc le coût si vous
  payez à la minute). Attention : cela décale les horodatages du transcript.
- **Découper en segments** — pour les services qui limitent la taille des fichiers.

---

## Transcription

Dans le panneau **Installation** (colonne de droite), cliquez sur *Installer* en face de
« Moteur de transcription », puis sur *Télécharger* pour le modèle. Le journal s'affiche
pendant l'opération ; il n'y a rien d'autre à faire. Cochez ensuite **Transcrire après le
nettoyage**.
La transcription part toujours de l'audio nettoyé : c'est ce qui fait le plus pour la
qualité du verbatim.

### Modèles

| Modèle | Taille | Vitesse (portable sans carte graphique) | Qualité |
|---|---|---|---|
| tiny | 75 Mo | ~8× plus rapide que le temps réel | brouillon |
| base | 145 Mo | ~5× | approximative |
| small | 480 Mo | ~2× | correcte |
| medium | 1,5 Go | ~1× | bonne |
| **large-v3-turbo** | 1,6 Go | ~2× | très bonne — **le bon choix par défaut** |
| large-v3 | 3,1 Go | ~0,4× (2 h 30 pour 1 h) | la meilleure |

Le modèle se télécharge au premier usage, puis tout fonctionne hors ligne. Avec une carte
graphique NVIDIA, c'est automatiquement 5 à 10 fois plus rapide.

**Le réglage qui change le plus de choses** : le champ *Vocabulaire de la réunion*. Y mettre
les noms des participants, les sigles maison et les noms de produits améliore nettement les
noms propres — c'est là qu'un moteur générique se trompe le plus.

### Vérifier que ça marche chez vous

Dans le panneau **Installation**, la ligne *Vérifier sur cette machine* met le moteur à
l'épreuve en une minute et rend trois chiffres :

- **la vitesse réelle** sur votre machine — combien de minutes de calcul pour une heure de
  réunion. C'est ce qui doit guider le choix du modèle, bien plus que les estimations du
  tableau ci-dessus ;
- **le taux d'erreur**, mesuré sur trois phrases dont le texte exact est connu, lues par la
  voix de synthèse de votre système. Sous 12 % c'est très bon, jusqu'à 30 % ça reste
  relisible, au-delà il faut changer quelque chose ;
- **les hallucinations** : le moteur écoute 15 secondes de silence bruité et ne devrait
  produire aucun mot. S'il en invente, montez le débruitage.

Rien n'est envoyé nulle part et aucun fichier de référence n'est embarqué : l'extrait est
fabriqué sur place. Si votre système n'a pas de voix française installée, la précision n'est
pas mesurée — le reste l'est quand même, et l'outil vous le dit.

### Livrables

| Fichier | Contenu |
|---|---|
| `…_compte-rendu.docx` | temps de parole, relevé automatique, puis le verbatim complet |
| `…_verbatim.txt` | le verbatim seul, horodaté, en texte brut |
| `…_transcription.json` | segments, horodatages, intervenants, relevé — pour enchaîner un traitement |
| `….srt` | sous-titres, si vous devez recaler l'audio |

### Intervenants

Par défaut, l'outil sépare les tours de parole avec une méthode intégrée (MFCC +
regroupement), sans rien installer de plus. Sur des dialogues de référence à 1, 2 et 3 voix
distinctes, elle retrouve le bon nombre d'intervenants et attribue correctement 100 % du
temps de parole. Sur des voix proches, enregistrées par le même micro ou qui se coupent la
parole, elle sera moins fiable.

**Si vous connaissez le nombre de participants, indiquez-le** : c'est le réglage qui
sécurise le plus le résultat.

Pour une identification de niveau professionnel, le panneau **Installation** propose
« Identification avancée (pyannote) ». Un bouton l'installe (~2 Go, PyTorch). Il faut
ensuite un jeton gratuit :

1. créer un compte sur [huggingface.co](https://huggingface.co) ;
2. accepter les conditions du modèle « pyannote/speaker-diarization-3.1 » ;
3. créer un jeton d'accès et le **coller dans le champ prévu** dans le panneau Installation.

Le jeton est enregistré sur votre disque, aucune variable d'environnement à définir.
L'outil bascule alors automatiquement sur pyannote, et le document indique toujours quelle
méthode a servi.

### Relevé automatique : ce que c'est, et ce que ce n'est pas

Le compte rendu contient un **relevé par mots-clés** : décisions annoncées, actions
évoquées avec porteur et échéance, questions restées ouvertes, montants cités, déroulé.
C'est un outil de dépouillement — il pointe les passages à vérifier dans le verbatim.
Il ne comprend pas la réunion et ne remplace pas votre relecture.

Pour une vraie synthèse rédigée, sans rien envoyer sur Internet, installez
[Ollama](https://ollama.com) et un modèle (`ollama pull llama3.1`). L'outil le détecte tout
seul et ajoute une section **Synthèse** au document.

---

## Traitement automatique (section 5 de l'interface)

Cochez **Surveiller un dossier**, choisissez-le avec le bouton *Choisir*, et c'est réglé :
tout enregistrement déposé dans ce dossier est nettoyé, transcrit et mis en forme tout seul,
avec les réglages en cours. Pointez-le sur le dossier où votre logiciel de visio dépose ses
enregistrements et vous n'avez plus rien à lancer.

Quelques précisions utiles :

- les fichiers **déjà présents** au moment où vous activez la surveillance ne sont pas
  repris — seuls les nouveaux le sont ;
- un fichier en cours de copie est laissé tranquille jusqu'à ce que sa taille se stabilise ;
- les fichiers sont traités un par un, dans l'ordre d'arrivée ;
- laissez la fenêtre de l'outil ouverte : c'est elle qui surveille.

Le fichier `.json` produit à côté du compte rendu contient chaque segment avec son
horodatage, son intervenant et le relevé structuré — de quoi alimenter ensuite un tableur
ou un autre outil.

---

## En ligne de commande

```bash
python -m audiotool.cli reunion.m4a
python -m audiotool.cli *.m4a --preset salle_bruyante --out ./nettoyes
python -m audiotool.cli reunion.m4a --exports transcribe --segment-minutes 20
python -m audiotool.cli --serveur --port 7862      # relance l'interface web
python -m audiotool.cli --verifier                 # état du moteur de transcription
python -m audiotool.cli --telecharger-modele medium
python -m audiotool.cli --help                     # toutes les options
```

---

## Ce que fait la chaîne de traitement

Une passe d'analyse mesure le plancher de bruit, le niveau de parole et le profil
spectral du bruit, puis chaque bloc de 30 secondes traverse :

1. **Coupe-grave** (Butterworth ordre 4) + **réjecteurs** sur le secteur et ses harmoniques
2. **Débruitage spectral** — soustraction douce fondée sur le profil de bruit mesuré, avec
   lissage temps/fréquence du masque pour éviter le « bruit musical »
3. **Égalisation** — allègement du bas médium (résonance de pièce), relief de présence,
   shelf d'aigus adoucissant
4. **Expandeur** — baisse le fond entre les prises de parole, montée rapide pour ne pas
   hacher les débuts de mots
5. **Désesseur** — compression dynamique de la bande 5–9 kHz uniquement
6. **Compresseur** — genou progressif, détecteur RMS, seuil calé sur le niveau de parole mesuré
7. **Limiteur** à anticipation, puis **calage de sonie** ITU-R BS.1770 (LUFS)

Le traitement se fait en flux, par blocs, avec 1 seconde de contexte de part et d'autre :
mémoire constante quelle que soit la durée, et aucune couture audible.

**Performance mesurée** : une réunion d'une heure passe en environ 2 min 30 (analyse
comprise), avec moins de 400 Mo de mémoire.

---

## Vérification

```bash
python tests/test_dsp.py            # 14 tests unitaires du traitement du signal
python tests/test_transcription.py  # 39 tests : transcription, intervenants, livrables
python tests/make_sample.py         # fabrique une fausse réunion bruitée
python tests/evaluate.py            # mesure avant/après sur cet échantillon
```

Sur l'échantillon de test (souffle, ronflement 50 Hz, clics clavier, un intervenant 12 dB
plus faible) :

| Mesure | Avant | Après |
|---|---|---|
| Bruit de fond | −36,4 dB | −63,4 dB |
| Contraste parole / bruit | 16,2 dB | 43,1 dB |
| Ronflement 50 Hz | référence | −45 dB |
| Crête finale | — | −1,1 dBFS, aucun dépassement |

---

## Ce qui a été vérifié, et ce qui ne l'a pas été

Mesuré et testé : la chaîne audio, l'identification des intervenants (dialogues de
référence à 1, 2 et 3 voix), le relevé automatique, et l'écriture des quatre livrables.

Non testé de bout en bout : la transcription Whisper elle-même, qui demande de télécharger
le modèle. Le code suit l'interface publique de `faster-whisper`, et l'outil dit clairement
ce qui manque. Vérifiez chez vous avec :

```bash
python -m audiotool.cli --verifier
python -m audiotool.cli tests/reunion_test.m4a --transcrire --modele tiny
```

## Résolution de problèmes

| Symptôme | Cause probable |
|---|---|
| « ffmpeg est introuvable » | `pip install imageio-ffmpeg`, ou installez ffmpeg sur le système |
| Le navigateur ne s'ouvre pas | allez sur `http://127.0.0.1:7862` manuellement |
| Voix qui « ondule » ou sonne métallique | débruitage trop fort : redescendez vers 40–50 |
| Début de mots hachés | décochez « Atténuer le fond entre les prises de parole » |
| Le port 7862 est occupé | `python -m audiotool.cli --serveur --port 7900` |
| « Moteur non installé » | panneau *Installation*, bouton *Installer* |
| L'installation échoue | vérifiez la connexion internet ; certains réseaux d'entreprise bloquent les téléchargements |
| Réglages perdus | ils sont dans `reglages.json`, à côté des fichiers produits |
| Transcription très lente | prenez `small`, ou `large-v3-turbo` plutôt que `large-v3` |
| Noms propres massacrés | remplissez le champ *Vocabulaire de la réunion* |
| Intervenants mélangés | indiquez leur nombre, ou installez `pyannote.audio` |
| Phrases inventées dans les silences | augmentez le débruitage : Whisper hallucine sur du souffle |
