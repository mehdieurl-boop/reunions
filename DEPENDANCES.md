# Composants utilisés et leurs licences

Inventaire vérifié en août 2026. Il vaut la peine d'être relu avant toute exploitation
commerciale : ce document n'est pas un avis juridique.

## Bibliothèques Python

| Composant | Rôle | Licence | Usage commercial |
|---|---|---|---|
| numpy | calcul numérique | BSD-3-Clause | libre |
| scipy | filtres, FFT, regroupement | BSD-3-Clause | libre |
| Flask | serveur local de l'interface | BSD-3-Clause | libre |
| python-docx | écriture des documents Word | MIT | libre |
| imageio-ffmpeg | fournit un binaire ffmpeg | BSD-2-Clause pour l'enveloppe Python ; le binaire ffmpeg a sa propre licence (voir plus bas) | à vérifier selon le mode de distribution |
| faster-whisper | moteur de transcription | MIT (SYSTRAN) | libre |
| pyannote.audio | identification des intervenants (optionnel) | MIT | voir plus bas |

## Modèles

| Modèle | Licence | Remarque |
|---|---|---|
| Whisper (`tiny` → `large-v3`, `large-v3-turbo`) | MIT (OpenAI) | poids réutilisables, y compris commercialement |
| `pyannote/speaker-diarization-3.1` | MIT | accès conditionné à l'acceptation de conditions et au partage de coordonnées sur HuggingFace ; les auteurs orientent les usages en production vers leur offre payante **pyannoteAI**. La licence du modèle reste MIT. |

L'identification intégrée à cet outil (`audiotool/diarize.py`) ne dépend d'aucun modèle
externe : c'est du MFCC et du regroupement hiérarchique écrits ici. Si la question pyannote
devient gênante, elle peut être retirée sans casser l'outil.

## ffmpeg — le point à surveiller

ffmpeg est sous **LGPL v2.1**, sauf s'il est compilé avec `--enable-gpl` (ou avec des
bibliothèques GPL comme libx264), auquel cas **tout ffmpeg passe sous GPL**.

Dans ce projet, ffmpeg n'est **pas redistribué** : il est soit déjà présent sur la machine,
soit installé par `pip install imageio-ffmpeg` chez l'utilisateur. C'est la position la plus
confortable — appeler un exécutable installé par ailleurs n'est pas une redistribution.

En revanche, **si vous fabriquez un installeur clé en main contenant ffmpeg**, les obligations
LGPL s'appliquent : liaison dynamique, mise à disposition du code source de ffmpeg avec les
instructions de compilation, mention de la licence dans l'application et sur la page de
téléchargement, et interdiction de renommer ou masquer les binaires. Vérifiez alors avec
quelles options le binaire embarqué a été compilé.

Côté brevets : les brevets MP3 ont expiré en 2017, ceux du cœur AAC sont également expirés.
Le sujet reste à regarder si vous ajoutez des formats vidéo (H.264, HEVC).

## Conséquence pour ce projet

L'outil est publié sous GPL-3.0. Cela n'entre en conflit avec aucune des licences ci-dessus
(MIT et BSD sont compatibles avec la GPL, et ffmpeg n'est pas redistribué).

En tant qu'auteur unique, vous conservez le droit de proposer le même code sous une autre
licence à des clients qui en auraient besoin — la GPL s'applique à ceux qui reçoivent le
logiciel, pas à vous.

## Sources

- [Licence de faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE)
- [Fiche du modèle pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
- [Fiche du modèle Whisper large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo)
- [FFmpeg — licence et considérations légales](https://ffmpeg.org/legal.html)
