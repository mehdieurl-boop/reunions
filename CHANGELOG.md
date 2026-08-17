# Journal des versions

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
- 14 tests du traitement du signal, 28 tests de la chaîne de transcription.
- Mesure avant/après sur un échantillon bruité reproductible.
- Intégration continue sur macOS, Windows et Linux.
