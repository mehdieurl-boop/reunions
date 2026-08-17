# Contribuer

## Repères

- Le projet ne dépend que de **numpy, scipy, Flask, python-docx** et de **ffmpeg**. Toute
  nouvelle dépendance doit se justifier : l'installation chez l'utilisateur final est une
  contrainte de conception, pas un détail.
- Le code et les commentaires sont **en français**. Les commentaires expliquent *pourquoi*,
  pas *quoi* — en particulier pour le traitement du signal, où un choix apparemment anodin
  (détecteur RMS plutôt que crête, absence de normalisation avant regroupement) a des raisons
  précises, souvent notées sur place.
- Le traitement audio est **vectorisé** : pas de boucle Python à l'échelle de l'échantillon.
  Une heure d'audio représente 172 millions d'échantillons.

## Avant de proposer une modification

```bash
python tests/test_dsp.py
python tests/test_transcription.py
python tests/make_sample.py && python tests/evaluate.py
```

Les trois doivent afficher `RÉSULTAT : OK`. L'intégration continue les rejoue sur macOS,
Windows et Linux.

Si vous touchez au traitement du signal, **ajoutez une mesure**, pas seulement un test de
non-plantage : `tests/test_dsp.py` vérifie des valeurs attendues (un compresseur 4:1 doit
réduire un palier de 15 dB à 3,8 dB, un limiteur ne doit jamais dépasser son plafond). Un test
qui vérifie seulement l'absence d'exception ne protège de rien.

## Organisation

| Fichier | Rôle |
|---|---|
| `audiotool/dsp.py` | briques de traitement du signal, sans état |
| `audiotool/pipeline.py` | enchaînement, découpage en blocs, exports |
| `audiotool/ffmpeg_io.py` | décodage et encodage |
| `audiotool/transcribe.py` | moteur de transcription (et moteur factice pour les tests) |
| `audiotool/diarize.py` | identification des intervenants |
| `audiotool/minutes.py` | relevé de décisions par règles |
| `audiotool/documents.py` | écriture des livrables |
| `audiotool/server.py` | serveur local et API |
| `audiotool/static/index.html` | interface, en un seul fichier |
| `audiotool/watcher.py` | dossier surveillé |
| `audiotool/setup_tools.py` | installation des composants depuis l'interface |

Le moteur factice (`--moteur mock`) permet de travailler sur tout ce qui vient après la
transcription sans télécharger de modèle.

## Ce qui aiderait le plus

- Des retours sur de vrais enregistrements (voir [TESTEURS.md](TESTEURS.md)).
- Enrichir les tournures détectées dans `minutes.py` — décisions, actions, échéances.
- Améliorer l'identification des intervenants sur des voix proches.
- Vérifier le comportement sous Windows, moins éprouvé que macOS et Linux.
