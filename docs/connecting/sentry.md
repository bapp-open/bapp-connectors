# Sentry

## Ce da conectorul
Proiectele organizatiei, issue-urile (erorile grupate: citire, filtrare dupa stare si mediu, rezolvare, redeschidere,
ignorare, asignare) si statisticile de evenimente pe proiect, pe sentry.io sau pe o instanta self-hosted.
Webhook-urile integrarii (evenimentele "issue") sunt verificate si traduse in evenimente.

## Token
Recomandat: o **internal integration**, ca sa nu depinda de contul unei persoane.
1. Settings > **Developer Settings** > **Custom Integrations** (pe versiunile mai vechi: *Internal Integrations*) >
   Create New Integration > Internal Integration.
2. Permisiuni: **Project: Read**, **Issue & Event: Read & Write** (Write e necesar pentru rezolvare / redeschidere;
   doar citire: **Issue & Event: Read**).
3. Salveaza, apoi copiaza token-ul generat de integrare.
4. Pentru webhook-uri (vezi mai jos): copiaza si **Client Secret**-ul integrarii.

Merge si un **User Auth Token** personal (User Settings > Auth Tokens) cu scope-urile
`org:read project:read event:read event:write`, dar e legat de o persoana: dispare odata cu contul ei.

## Credentiale
| Camp | Ce pui |
|------|--------|
| `host` | Doar hostname-ul, fara `https://` si fara cale: `sentry.io` pentru serviciul gazduit sau `sentry.example.net` pentru o instanta self-hosted |
| `organization` | Slug-ul organizatiei, cel din URL (`https://sentry.example.net/organizations/example-org/`): `example-org` |
| `token` | Token-ul de mai sus |
| `webhook_secret` | Optional. *Client Secret*-ul integrarii. Obligatoriu pentru webhook-uri: orice livrare nesemnata sau semnata cu alt secret e respinsa |

## Setari
- `stats_period`: fereastra pe care aplicatia o foloseste cand listeaza issue-urile nerezolvate (implicit `14d`;
  exemple: `24h`, `7d`, `14d`).
- `environment`: optional, filtreaza issue-urile pe un singur mediu (de ex. `production`). Gol = toate mediile.
- `verify_ssl`: verifica certificatul TLS (implicit da; dezactiveaza doar pentru instante interne cu certificat propriu).
- `timeout`: secunde per cerere (implicit 30).

## Webhook
1. Pe internal integration-ul de mai sus: **Webhook URL** = cel din popover-ul conexiunii in aplicatie.
2. La *Webhooks*, activeaza resursa **issue** (creat, rezolvat, asignat, ignorat).
3. Pune *Client Secret*-ul integrarii in `webhook_secret` al conexiunii. Fara el, toate livrarile sunt respinse.

Webhook-urile Sentry se configureaza doar pe integrare; conectorul nu le poate inregistra singur prin API.

## Limite
Sentry aplica limite pe organizatie si pe token. Conectorul isi limiteaza singur ritmul la 5 cereri pe secunda si
reincearca automat cu backoff la 429, la erorile 5xx si la raspunsul sporadic `{"detail": "Internal Error"}` pe care
unele instante il dau la cereri valide.
