# Steam (Steamworks)

## Ce da conectorul
Vanzari detaliate pe zi (unitati, brut, retururi, taxe, net in USD), rambursari si recenziile publice ale aplicatiilor.
Comisionul Valve (30%, minus bonusul de tier) e **estimat** din `net_sales_usd`; se confirma cu raportul lunar din partner site.

## Credentiale
1. Steamworks > Users & Permissions > Manage Groups > **Create new group** de tip Financial API Group.
2. Pe pagina grupului: **Web API Key** (cheia financiara, `financial_api_key`) si **Manage WebAPI Key > Whitelisted IPs**: adauga IP-ul de iesire al
   serverului BAPP (altfel 403).
3. `app_ids`: id-urile aplicatiilor, separate prin virgula.

## Capcane
- Valve **revizuieste zile deja raportate**; `SteamAdapter.changed_dates(highwatermark)` da zilele de re-adus.
- Fara raspuns la recenzii, abonamente sau webhooks.
- `payout_id = "YYYY-MM:USD"`.
