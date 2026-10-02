# Apple App Store

## Ce da conectorul
Rapoarte de vanzari pe zi, rapoarte financiare pe luna fiscala (decontari per moneda), recenzii cu raspuns,
starea abonamentelor si notificarile App Store Server (cu cheia In-App Purchase).

## Credentiale
1. App Store Connect > Users and Access > Integrations > **App Store Connect API** > Generate API Key.
   Rol: **Finance** (sau Admin). Noteaza *Issuer ID*, *Key ID* si descarca `AuthKey_<KEYID>.p8` (o singura data).
2. *Vendor Number*: App Store Connect > Payments and Financial Reports (sus, 8 cifre).
3. Pentru abonamente si notificari: Users and Access > Integrations > **In-App Purchase** > Generate (alta cheie!),
   plus *Bundle ID*-ul aplicatiei.
4. Notificari: App Store Connect > App > App Information > App Store Server Notifications > URL-ul = webhook-ul conexiunii,
   versiunea 2. **Production si Sandbox cer conexiuni SEPARATE**: una cu `server_api_environment=production` (URL-ul ei
   la Production) si una cu `server_api_environment=sandbox` (URL-ul ei la Sandbox), pentru ca adapterul respinge
   notificarile din celalalt mediu.

## Capcane
- Raportul financiar se cere pe **luna fiscala Apple**, nu calendaristica; adapterul traduce singur. Calendarul e calculat din regula Apple: anul fiscal se incheie in ultima sambata din septembrie, luni de 5-4-4 saptamani (in anii de 53 de saptamani decembrie are 5).
- Apple plateste la ~33 de zile dupa inchiderea lunii fiscale, **per moneda**; `payout_id = "<luna fiscala>:<moneda>"`.
- Cheia `.p8` lipita cu `\n` literal e normalizata automat.
- `Partner Share` e deja net de comision si taxe: la Apple brut = net.
- Notificarile sunt acceptate doar daca lantul x5c are exact 3 certificate cu OID-urile Apple, iar `bundleId`/`environment` din notificare coincid cu conexiunea (bundle_id, server_api_environment).
