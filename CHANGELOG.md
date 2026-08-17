# Journal des versions

## 1.2.0

**Les débuts de mots ne sont plus rabotés par le débruiteur**

Signalé par le cadrage d'intégration avec Verbatim (issue #1), mesuré, puis corrigé.

- Le masque du débruiteur spectral était lissé de façon **symétrique** dans le temps.
  Au démarrage d'un mot, il restait fermé par le silence qui précédait et mettait deux à
  trois trames à s'ouvrir. Mesure sur 44 prises de parole : **−5,4 dB en moyenne sur les
  50 premières millisecondes**, pire cas −15,7 dB, 34 débuts sur 44 au-delà de 3 dB.
- Ni la porte de bruit ni le compresseur n'étaient en cause : désactivés l'un après
  l'autre, la mesure ne bougeait pas ; débruitage désactivé, elle tombait à −0,55 dB.
- Le lissage temporel ne regarde désormais que **vers l'avant** ([t, t+8]) : le masque est
  déjà ouvert quand la voix arrive. Résultat : **−1,42 dB en moyenne**, 12 débuts sur 44
  au-delà de 3 dB, pour environ 1 dB de bruit de fond en moins bien.
- Un retour lent (masque maintenu ouvert après la parole) a été essayé et écarté : 3 dB de
  bruit de fond perdus sans bénéfice sur les attaques. C'est noté dans le code.
- Test de non-régression ajouté : `tests/test_dsp.py` compare la tête d'une salve à son
  corps ; le lissage centré échoue à ce test.

## 1.1.1

**Correctifs Windows**

- La sortie console est forcée en UTF-8 : sans cela, les tests et la ligne de commande
  s'arrêtaient sur une `UnicodeEncodeError` dès le premier caractère « ✓ » ou « █ »,
  la console Windows utilisant la page de code 1252.
- Bit d'exécution rétabli sur `Demarrer_Mac_Linux.command` : perdu lors d'une modification
  via l'éditeur web de GitHub, il empêchait le lancement par double-clic sous macOS et Linux.
- Variables `PYTHONUTF8` et `PYTHONIOENCODING` posées dans l'intégration continue.

## 1.1.0

**Vérification du moteur sur la machine de l'utilisateur**

- Bouton *Vérifier sur cette machine* dans le panneau Installation.
- Fabrique un extrait parlé avec la voix de synthèse du système (Windows SAPI, `say` sous
  macOS, espeak sous Linux) : aucun fichier de référence n'est embarqué.
- Mesure le taux d'erreur sur les mots (avec distinction substitutions / omissions /
  insertions), la vitesse réelle en facteur temps réel, et le nombre de mots inventés sur
  15 secondes de silence bruité.
- Verdict en clair, avec la conduite à tenir selon le résultat.
- Dégradation propre si le système n'a pas de voix française : les autres mesures sont
  quand même rendues.

## 1.0.0

Première version publiée.

**Nettoyage audio**
- Chaîne complète : coupe-grave, réjecteurs secteur avec détection automatique 50/60 Hz,
  débruitage spectral, égalisation adoucissante, expandeur, désesseur, compresseur, limiteur.
- Calage de sonie ITU-R BS.1770-4, mesuré en flux.
- Traitement par blocs de 30 s avec 1 s de contexte : mémoire constante, pas de couture audible.
- Deux exports : écoute (−16 LUFS) et transcription (WAV mono 16 kHz, −20 LUFS).
- Quatre préréglages, aperçu A/B de 20 secondes à volume égalisé.

**Transcription**
- faster-whisper en local, modèles `tiny` à `large-v3`.
- Champ de vocabulaire (noms propres, sigles).
- Identification des intervenants : méthode intégrée MFCC + regroupement, ou pyannote.audio.
- Livrables : compte rendu Word, verbatim texte, sous-titres SRT, données JSON.
- Relevé automatique par règles : décisions, actions avec porteur et échéance, questions
  ouvertes, montants, déroulé, temps de parole.
- Synthèse rédigée optionnelle via un modèle local (Ollama), détecté automatiquement.

**Interface**
- Tout se pilote depuis la page : installation des composants, téléchargement des modèles,
  jeton HuggingFace, choix des dossiers.
- Dossier surveillé : traitement automatique des nouveaux enregistrements.
- Réglages mémorisés sur le disque.

**Vérification**
- 14 tests du traitement du signal, 39 tests de la chaîne de transcription.
- Mesure avant/après sur un échantillon bruité reproductible.
- Intégration continue sur macOS, Windows et Linux.
