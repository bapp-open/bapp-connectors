# Google Play

## Ce da conectorul
Rapoartele de venituri (`earnings/`) si vanzari (`sales/`) din bucket-ul Cloud Storage, recenziile (istoric din CSV,
proaspete din API) cu raspuns, cumparaturile anulate, starea abonamentelor si notificarile RTDN prin Pub/Sub.

## Credentiale
1. Google Cloud Console > IAM > Service Accounts > Create > Keys > **JSON**. Lipeste JSON-ul intreg in `service_account_json`.
2. Play Console > Users and permissions > Invite new user > email-ul service account-ului; permisiuni:
   **View financial data**, **Reply to reviews**, **Manage orders and subscriptions** (pentru voided purchases / subscriptionsv2).
3. Play Console > Download reports > Financial > **Copy Cloud Storage URI** -> `bucket_uri` (`gs://pubsite_prod_rev_...`).
4. `package_names`: pachetele aplicatiilor, separate prin virgula.
5. Notificari: Play Console > Monetization setup > Real-time developer notifications > topic Pub/Sub; in Cloud Console
   creeaza o subscriptie **push** catre webhook-ul conexiunii. Daca activezi autentificarea push (OIDC), pune audience-ul in
   `pubsub_audience`.

## Capcane
- Raportul lunii apare in jurul datei de 5 a lunii urmatoare; pana atunci pagina e goala, nu eroare.
- `reviews.list` din API da **doar ultimele 7 zile**; istoricul vine din CSV-urile lunare (UTF-16).
- `voidedpurchases` tine **30 de zile** inapoi.
- `payout_id = "YYYYMM:<moneda comerciantului>"`, o plata pe luna.
- Push-ul Pub/Sub e acceptat fara token OIDC cand `pubsub_audience` e gol; cu audience setat, tokenul e verificat (RS256, iss Google, aud) si cheile JWKS se re-aduc o data la `kid` necunoscut.
