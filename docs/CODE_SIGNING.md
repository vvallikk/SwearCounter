# Политика подписи кода · Code signing policy

Подана заявка на бесплатную подпись кода от [SignPath.io](https://about.signpath.io/)
с сертификатом [SignPath Foundation](https://signpath.org/). Пока её не одобрили, exe
не подписан; после одобрения его будет подписывать этот сертификат по правилам ниже.

We have applied for free code signing provided by [SignPath.io](https://about.signpath.io/),
with a certificate by [SignPath Foundation](https://signpath.org/). Until the application
is approved the exe is not signed; after that it will be signed with this certificate
under the rules below.

## Что подписывается · What is signed

- `SwearCounter.exe` из архива `SwearCounter-vX.Y.Z-windows.zip` на странице
  [релизов](https://github.com/vvallikk/SwearCounter/releases).
- Exe собирается из исходного кода этого репозитория в GitHub Actions
  ([release.yml](../.github/workflows/release.yml)) по тегу версии и только потом
  отправляется на подпись. Вручную собранные файлы не подписываются.
- Каждый запрос подписи вручную подтверждает утверждающий (см. ниже).

- `SwearCounter.exe` inside `SwearCounter-vX.Y.Z-windows.zip` on the
  [releases](https://github.com/vvallikk/SwearCounter/releases) page.
- The exe is built from this repository's source code by GitHub Actions
  ([release.yml](../.github/workflows/release.yml)) on a version tag and only then
  submitted for signing. Locally built files are never signed.
- Every signing request is manually approved by an approver (see below).

## Роли · Team roles

| Роль · Role | Участники · Members |
|---|---|
| Авторы и ревьюеры · Committers and reviewers | [vvallikk](https://github.com/vvallikk) |
| Утверждающие · Approvers | [vvallikk](https://github.com/vvallikk) |

## Приватность · Privacy policy

Программа не передаёт никаких данных в другие сетевые системы, кроме случаев,
перечисленных ниже. Звук с микрофона и распознанный текст не сохраняются и никуда
не отправляются: речь распознаётся на компьютере пользователя.

- Проверка обновлений: запрос списка релизов к API GitHub. Автопроверку при запуске
  можно отключить в разделе "Обновления".
- Скачивание моделей распознавания и обновлений: только по кнопке пользователя.
- Установка оформления по ссылке: только по ссылке, которую вставил пользователь.

This program will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it, with the
exceptions listed below. Microphone audio and recognized text are never stored or sent
anywhere: speech is recognized locally on the user's computer.

- Update check: a request to the GitHub API for the list of releases. The automatic
  check on startup can be turned off in the "Обновления" (Updates) section.
- Downloading speech models and updates: only when the user presses the button.
- Installing a style from a link: only from a link the user pasted.
