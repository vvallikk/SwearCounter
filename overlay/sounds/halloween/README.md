# Звуки события «Хеллоуин» (временные)

Встроенные звуки события `halloween` (app/events.py). Их видно в списке звуков и они играют
только во время события, с 15 октября по 1 ноября включительно. После события папку можно удалить
целиком: программа работает и без неё (вместо файлов играют синтезированные замены из overlay/sound.js).

Все исходники — **CC0 1.0** (общественное достояние, https://creativecommons.org/publicdomain/zero/1.0/):
их можно использовать, менять и распространять без указания автора. Авторов всё равно перечисляем.

| Файл | Что это | Из чего собран (источник, автор, CC0) |
|---|---|---|
| scream-stab.ogg | Скример: настоящий женский крик с перегрузом + удар | [Female Scream 1](https://opengameart.org/content/female-scream-1) (mightydinosaurcol), `Bassy 5.wav` из [Horror Hit Soundpack 1](https://opengameart.org/content/horror-hit-soundpack-1) (psychhead_), щелчок |
| ghost-shriek.ogg | Визг призрака: хриплый вопль с сильным перегрузом + низкий удар | [Female high-pitched scream SFX](https://opengameart.org/content/female-high-pitched-scream-sfx), `screams_0.ogg` (bitetti), `Very Bassy 1.wav` из [Horror Hit Soundpack 1](https://opengameart.org/content/horror-hit-soundpack-1) (psychhead_), щелчок |
| banshee.ogg | Крик банши: ускоренный женский крик + пронзительный слой | [Female Scream 1](https://opengameart.org/content/female-scream-1) (mightydinosaurcol), [High pitch scream sounds(2)](https://opengameart.org/content/high-pitch-scream-sounds2), `high_pitch_scream.mp3` (looneybits), щелчок |
| jumpscare-hit.ogg | Удар-скример: удар и короткий обрубленный крик | `Bassy 5.wav` из [Horror Hit Soundpack 1](https://opengameart.org/content/horror-hit-soundpack-1) (psychhead_), [Female Scream 1](https://opengameart.org/content/female-scream-1) (mightydinosaurcol), щелчок |
| jumpscare-low.ogg | Низкий удар-скример: низкий удар и замедленный вопль | `Very Bassy 1.wav` оттуда же (psychhead_), `screams_0.ogg` (bitetti), щелчок |
| ghost-moan.ogg | Стон призрака | [Ghost Monster Voice Moaning & Growling](https://opengameart.org/content/ghost-monster-voice-moaning-growling), `qubodup-GhostMoan01` (qubodup) |
| witch-cackle.ogg | Смех ведьмы | [Witch Cackle](https://opengameart.org/content/witch-cackle), `witch_cackle-1.ogg` (AntumDeluge) |
| evil-laugh.ogg | Злой смех (звук проклятия) | [Evil Laugh](https://opengameart.org/content/evil-laugh), `laugh-evil-1.ogg` (AntumDeluge) |
| demon-laugh.ogg | Демонический хохот | [Evil Laughs Pack](https://opengameart.org/content/evil-laughs-pack), `Laugh 7.mp3`, с 1,3 с (Eldritch Grim) |
| door-creak.ogg | Скрип двери | [Creaky Door Hinge Spooky](https://opengameart.org/content/creaky-door-hinge-spooky), `creaky_door_hinge.wav` (w.forster.1) |

Крики перегружаются (`tanh`-ограничитель), как у скримеров в играх. Синтезированные слои («удар смычком» — кластер из пяти соседних полутонов, и щелчок в начале)
генерирует `scripts/halloween_sounds.py`; это работа проекта, она тоже отдаётся в CC0.

Лицензия проверена на странице каждого источника 29.10.2026 (крики — 31.10.2026). Звуки с CC-BY и другими лицензиями
с указанием автора намеренно не брались.

Сборка: `python scripts/halloween_sounds.py <папка с исходниками>` (нужны numpy и ffmpeg).
Тишина в начале срезается, атака жёсткая, затем компрессор, выравнивание громкости
`loudnorm=I=-14:TP=-1` и ограничитель, OGG Vorbis q5.
