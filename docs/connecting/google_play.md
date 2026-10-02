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
   `pubsub_audience` si contul de serviciu ales la „Enable authentication” in `pubsub_service_account_email`
   (amandoua sau niciunul: audience fara email = toate notificarile sunt respinse).

## Capcane
- Raportul lunii apare in jurul datei de 5 a lunii urmatoare; pana atunci pagina e goala, nu eroare.
- `reviews.list` din API da **doar ultimele 7 zile**; istoricul vine din CSV-urile lunare (UTF-16).
- `voidedpurchases` tine **30 de zile** inapoi.
- `payout_id = "YYYYMM:<moneda comerciantului>"`, o plata pe luna.
- **Fara `pubsub_audience` push-ul e acceptat NEVERIFICAT**: oricine stie URL-ul webhook-ului poate trimite notificari.
  Cu audience setat, tokenul e verificat (RS256, iss Google, aud, `email` = `pubsub_service_account_email` cu
  `email_verified`) si cheile JWKS se re-aduc o data la `kid` necunoscut.
- Notificarile RTDN sunt doar **semnale**: nu poarta starea abonamentului. Starea se reciteste mereu cu
  `get_subscription` (subscriptionsv2) inainte de orice decizie (acces, facturare).
