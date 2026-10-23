# GitLab

## Ce da conectorul
Proiectele (inclusiv din subgrupuri), issue-urile (citire, creare, editare, inchidere, comentarii), merge request-urile,
commit-urile si pipeline-urile, pe gitlab.com sau pe o instanta self-managed. Webhook-urile GitLab (push, issues,
merge requests, pipelines, comentarii) sunt verificate si traduse in evenimente.

## Token
Recomandat: un **group access token**, ca sa nu depinda de contul unei persoane.
1. Grupul > Settings > **Access tokens** > Add new token.
2. Rol **Maintainer**, scope **`api`**: functionalitate completa, inclusiv inregistrarea automata a webhook-ului.
3. Doar citire: rol **Reporter**, scope **`read_api`** (fara creare de issue-uri si fara webhook automat).
4. Copiaza token-ul imediat; GitLab il arata o singura data. Pune o data de expirare si noteaz-o.

Merge si un **personal access token** (User Settings > Access tokens) sau un **project access token**
(Proiectul > Settings > Access tokens), cu aceleasi scope-uri. Un token de proiect vede doar proiectul lui.

## Credentiale
| Camp | Ce pui |
|------|--------|
| `host` | Doar hostname-ul, fara `https://` si fara cale: `gitlab.com` sau `git.example.net` |
| `token` | Token-ul de mai sus |
| `webhook_secret` | Optional pentru API, **obligatoriu pentru webhook-uri**: *Secret token*-ul pus pe webhook-ul GitLab (vezi mai jos). Fara el, orice livrare e respinsa |

## Setari
- `groups`: grupurile indexate, separate prin virgula, cu calea completa (subgrupurile merg: `platform,platform/tools`).
  Proiectele din subgrupuri sunt incluse automat. Gol = toate proiectele la care token-ul are acces.
- `include_archived`: include si proiectele arhivate (implicit nu).
- `verify_ssl`: verifica certificatul TLS (implicit da; dezactiveaza doar pentru instante interne cu certificat propriu).
- `timeout`: secunde per cerere (implicit 30).

## Webhook
1. Proiectul > Settings > **Webhooks** > Add new webhook.
2. URL: cel din popover-ul conexiunii in aplicatie.
3. *Secret token*: acelasi sir ca in `webhook_secret` al conexiunii (obligatoriu). Daca lipseste sau difera, evenimentele sunt respinse.
4. Evenimente: **Push**, **Issues**, **Merge requests**, **Pipelines**, **Comments**.
5. Lasa "Enable SSL verification" bifat.

Cu un token de rol Maintainer, conectorul poate inregistra webhook-ul singur (`register_webhook`, per proiect), cu
aceleasi evenimente si cu secretul din conexiune. Refuza fara `webhook_secret`, iar daca proiectul are deja un webhook
cu acelasi URL nu creeaza altul: il intoarce pe cel existent.

## Limite
Instantele self-managed au implicit limite generoase (configurabile de admin in Admin > Settings > Network);
gitlab.com aplica limitele lui pe utilizator. Conectorul isi limiteaza singur ritmul la 10 cereri pe secunda si
reincearca automat cu backoff la 429 (respectand `Retry-After`) si la erorile temporare.
