# Steam (Steamworks)

## Ce da conectorul
Vanzari detaliate pe zi (unitati, brut, retururi, taxe, net in USD), rambursari si recenziile publice ale aplicatiilor.
Comisionul Valve (30%, minus bonusul de tier) e **estimat** din `net_sales_usd`; se confirma cu raportul lunar din partner site.

## Statistici
- **Wishlist**: `get_app_stats` aduce cate o zi pe pagina, prin cheia financiara (`GetAppWishlistReporting`), incepand de la `app_min_date` a aplicatiei: adaugari, stergeri, achizitii si cadouri, ca total pe zi si pe tara (randurile pe tara nule se omit; o zi fara activitate da lista goala). Totalul adaugarilor poarta in `extra` platformele (windows/mac/linux). Valve poate revizui zilele recente, deci re-adu ultimele zile.
- **Jucatori curenti** (`CURRENT_PLAYERS`): endpoint public, fara cheie, doar pentru ziua de azi; daca nu raspunde, raportul de wishlist iese oricum.

## Credentiale
1. Steamworks > Users & Permissions > Manage Groups > **Create new group** de tip Financial API Group.
2. Pe pagina grupului: **Web API Key** (cheia financiara, `financial_api_key`) si **Manage WebAPI Key > Whitelisted IPs**: adauga IP-ul de iesire al
   serverului BAPP (altfel 403).
3. `app_ids`: id-urile aplicatiilor, separate prin virgula.

## Capcane
- Valve **revizuieste zile deja raportate**; `SteamAdapter.changed_dates(highwatermark)` da zilele de re-adus.
- Retururile vin de la Steam cu **semn negativ** pe unitati (`gross_units_returned`), suma (`gross_returns_usd`) si taxa (`net_tax_usd`, taxa inversata); conectorul normalizeaza: RETURN <= 0, `AppStoreRefund.amount` >= 0, iar `net_sales = gross + returns - tax` cu semnele originale.
- Fara raspuns la recenzii, abonamente sau webhooks.
- `payout_id = "YYYY-MM:USD"`.
