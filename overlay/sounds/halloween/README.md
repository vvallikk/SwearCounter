# Звуки события «Хеллоуин» (временные)

Встроенные звуки события `halloween` (app/events.py). Их видно в списке звуков и они играют
только во время события, с 15 октября по 1 ноября включительно. После события папку можно удалить
целиком: программа работает и без неё (вместо файлов играют синтезированные замены из overlay/sound.js).

Все исходники — **CC0 1.0** (общественное достояние, https://creativecommons.org/publicdomain/zero/1.0/):
их можно использовать, менять и распространять без указания автора. Авторов всё равно перечисляем.

| Файл | Что это | Источник | Автор | Лицензия |
|---|---|---|---|---|
| ghost-shriek.ogg | Визг призрака | [Scary High-pitched Ghost](https://opengameart.org/content/scary-high-pitched-ghost), `scaryhighpitchedghost.ogg`, 9,0–12,6 с | Fupi | CC0 |
| jumpscare-hit.ogg | Удар-скример | [Horror Hit Soundpack 1](https://opengameart.org/content/horror-hit-soundpack-1), `Bassy 5.wav`, 0–3 с | psychhead_ | CC0 |
| jumpscare-low.ogg | Низкий удар-скример | [Horror Hit Soundpack 1](https://opengameart.org/content/horror-hit-soundpack-1), `Very Bassy 1.wav`, 0–3 с | psychhead_ | CC0 |
| ghost-moan.ogg | Стон призрака | [Ghost Monster Voice Moaning & Growling](https://opengameart.org/content/ghost-monster-voice-moaning-growling), `qubodup-GhostMoan01` | qubodup | CC0 |
| witch-cackle.ogg | Смех ведьмы | [Witch Cackle](https://opengameart.org/content/witch-cackle), `witch_cackle-1.ogg` | AntumDeluge | CC0 |
| evil-laugh.ogg | Злой смех (звук проклятия) | [Evil Laugh](https://opengameart.org/content/evil-laugh), `laugh-evil-1.ogg` | AntumDeluge | CC0 |
| demon-laugh.ogg | Демонический хохот | [Evil Laughs Pack](https://opengameart.org/content/evil-laughs-pack), `Laugh 7.mp3`, 1,3–5,2 с | Eldritch Grim | CC0 |
| door-creak.ogg | Скрип двери | [Creaky Door Hinge Spooky](https://opengameart.org/content/creaky-door-hinge-spooky), `creaky_door_hinge.wav`, 0–3,15 с | w.forster.1 | CC0 |

Лицензия проверена на странице каждого источника 29.10.2026. Звуки с CC-BY и другими лицензиями
с указанием автора намеренно не брались.

Обработка (ffmpeg): вырезан фрагмент, моно 44,1 кГц, плавное начало и затухание, выравнивание
громкости `loudnorm=I=-16:TP=-1.5` и ограничитель, OGG Vorbis q4. Пример:

```
ffmpeg -ss 9.0 -to 12.6 -i scaryhighpitchedghost.ogg -ac 1 -ar 44100 \
  -af "afade=t=in:d=0.02,afade=t=out:st=3.0:d=0.6,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100,alimiter=limit=0.84:level=false" \
  -c:a libvorbis -q:a 4 ghost-shriek.ogg
```
