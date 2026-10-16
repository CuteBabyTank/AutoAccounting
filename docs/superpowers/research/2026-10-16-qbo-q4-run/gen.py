import csv, os
from decimal import Decimal as D
OUT = os.path.join(os.path.dirname(__file__), "qbo")
def w(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        c = csv.writer(f); c.writerow(header); c.writerows(rows)

# ---- Chart of accounts ----
w("01_accounts.csv", ["Account Name", "Type", "Detail Type", "Description"], [
 ["Pinoy Commerce Bank - Checking 0041-2288-7710", "Bank", "Bank", "Business checking"],
 ["Cash on hand", "Bank", "Cash on hand", "Petty cash / store cash, e-wallets and other cards"],
 ["Credit card ****4412", "Credit Card", "Credit Card", "Company credit card ending 4412"],
 ["Input VAT", "Other Current Assets", "Other current assets", "Input VAT on domestic purchases"],
 ["Input VAT - Importation", "Other Current Assets", "Other current assets", "VAT paid to BOC on imports"],
 ["Creditable withholding tax", "Other Current Assets", "Other current assets", "EWT withheld by customers (2307 to receive)"],
 ["Office equipment", "Fixed Assets", "Machinery and equipment", "Computers and office equipment"],
 ["Output VAT", "Other Current Liabilities", "Other current liabilities", "VAT on sales"],
 ["Expanded withholding tax payable", "Other Current Liabilities", "Other current liabilities", "EWT withheld from suppliers (0619-E/1601-EQ)"],
 ["Withholding tax on compensation payable", "Other Current Liabilities", "Other current liabilities", "1601-C"],
 ["SSS payable", "Other Current Liabilities", "Other current liabilities", ""],
 ["PhilHealth payable", "Other Current Liabilities", "Other current liabilities", ""],
 ["Pag-IBIG payable", "Other Current Liabilities", "Other current liabilities", ""],
 ["Suspense - for review", "Other Current Liabilities", "Other current liabilities", "Items needing client confirmation"],
 ["Purchases", "Cost of Goods Sold", "Supplies & Materials - COGS", "Goods for resale incl. import landed cost"],
 ["Taxes and licenses", "Expenses", "Taxes Paid", "Local permits, fees, DST"],
 ["Representation and entertainment", "Expenses", "Entertainment Meals", "Client meals and gifts"],
 ["Transportation and fuel", "Expenses", "Auto", "Fuel, tolls, parking, rides"],
 ["13th month pay and other benefits", "Expenses", "Payroll Expenses", ""],
])

# ---- Products ----
sales_items = {
 "Portland Cement 40kg":265, "Deformed Bar 10mm x 6m":245, "Deformed Bar 12mm x 6m":387.5,
 "Tie Wire #16":84, "Hollow Block 4in":18, "Plywood 1/4 Marine":690, "Common Nails 3in":93,
 "Elastomeric Paint White":1525, "GI Sheet Gauge 26 x 8ft":560, "Coco Lumber 2x3x10":185,
 "Cordless Drill 18V":4250, "Socket Wrench Set 40pc":2150, "Enamel Paint Black":1100,
 "PVC Pipe 4in x 3m":420, "THHN Wire #12 (150m)":1890, "LED Bulb 12W":180,
}
prod = [[n, "Non-inventory", f"{p:.2f}", "Sales - wholesale"] for n,p in sales_items.items()]
prod += [["Output VAT 12%", "Service", "", "Output VAT"],
         ["Creditable withholding tax", "Service", "", "Creditable withholding tax"]]
w("02_products.csv", ["Product/Service Name", "Type", "Sales Price / Rate", "Income Account"], prod)

# ---- Invoices ----
def inv(no, cust, date, due, terms, lines, vat, cwt=None):
    rows=[]
    for q,item,rate in lines:
        rows.append([no,cust,date,due,terms,item,item,q,f"{rate:.2f}",f"{D(str(q))*D(str(rate)):.2f}"])
    rows.append([no,cust,date,due,terms,"Output VAT 12%","Output VAT 12%",1,f"{vat:.2f}",f"{vat:.2f}"])
    if cwt: rows.append([no,cust,date,due,terms,"Creditable withholding tax","1% EWT withheld by customer (2307 to follow)",-1,f"{cwt:.2f}",f"{-cwt:.2f}"])
    return rows
invs = []
invs += inv("0005","Mabuhay Builders Inc.","10/03/2026","11/02/2026","Net 30",[
 (140,"Portland Cement 40kg",265),(56,"Deformed Bar 10mm x 6m",245),(28,"Deformed Bar 12mm x 6m",387.5),
 (35,"Tie Wire #16",84),(70,"Hollow Block 4in",18),(14,"Plywood 1/4 Marine",690),(42,"Common Nails 3in",93),
 (17,"Elastomeric Paint White",1525)], 12643.32)
invs += inv("0006","Kalayaan Construction Co.","10/18/2026","11/17/2026","Net 30",[
 (420,"Portland Cement 40kg",265),(168,"Deformed Bar 12mm x 6m",387.5),(84,"GI Sheet Gauge 26 x 8ft",560),
 (98,"Coco Lumber 2x3x10",185)], 28988.40, cwt=2415.70)
invs += inv("0008","Mabuhay Builders Inc.","12/10/2026","01/09/2027","Net 30",[
 (210,"Portland Cement 40kg",265),(84,"PVC Pipe 4in x 3m",420),(14,"THHN Wire #12 (150m)",1890)], 14086.80)
w("03_invoices.csv", ["Invoice No","Customer","Invoice Date","Due Date","Terms","Product/Service","Description","Qty","Rate","Amount"], invs)

# ---- Sales receipts ----
def sr(no,cust,date,lines,vat):
    rows=[[no,cust,date,"Cash on hand",item,item,q,f"{rate:.2f}",f"{D(str(q))*D(str(rate)):.2f}"] for q,item,rate in lines]
    rows.append([no,cust,date,"Cash on hand","Output VAT 12%","Output VAT 12%",1,f"{vat:.2f}",f"{vat:.2f}"])
    return rows
srs = sr("0007","Juan Dela Cruz","11/22/2026",[(3,"Cordless Drill 18V",4250),(1,"Socket Wrench Set 40pc",2150),(4,"Enamel Paint Black",1100)],2316)
srs += sr("0009","San Roque Parish Church","12/20/2026",[(20,"Elastomeric Paint White",1525),(40,"LED Bulb 12W",180)],4524)
w("04_sales_receipts.csv", ["Sales Receipt No","Customer","Sales Receipt Date","Deposit To","Product/Service","Description","Qty","Rate","Amount"], srs)

# ---- Bills ---- (no, supplier, date, due, terms, memo, [(account, desc, amount)], pay_acct)
CASH="Cash on hand"; CC="Credit card ****4412"; BANK="Pinoy Commerce Bank - Checking 0041-2288-7710"
IV="Input VAT"
bills = [
 ("88548","Pacific Steel & Cement Supply Inc.","10/01/2026","10/31/2026","Net 30","Terms: 30 days PDC",[("Purchases","Cement and deformed bars for resale",143060),(IV,"Input VAT 12%",17167.20)],None),
 ("5838","Luzon Paint Distributors Corp.","11/05/2026","11/20/2026","Net 15","",[("Purchases","Paints and thinner for resale",62580),(IV,"Input VAT 12%",7509.60)],None),
 ("10759","Techworld Computer Center Inc.","11/12/2026","11/12/2026","Due on receipt","2 laptops S/N TW-88412, TW-88413 + laser printer",[("Office equipment","2 laptops 14in Core i5 + laser printer",75000),(IV,"Input VAT 12% (capital goods)",9000)],CASH),
 ("2026-1524","Sta. Elena Realty Corp.","12/01/2026","12/01/2026","Due on receipt","Dec 2026 store rent; 5% EWT WC100 withheld, issue 2307",[("Rent or lease payments","Ground floor store space Dec 2026",30000),(IV,"Input VAT 12%",3600),("Expanded withholding tax payable","5% EWT WC100",-1500)],BANK),
 ("EB-7781-2525","Metro Luzon Electric Company","11/15/2026","11/25/2026","","Acct 4412-8890-01, 2,840 kWh Oct 14-Nov 13",[("Utilities","Electricity",8450),(IV,"Input VAT 12%",1014)],None),
 ("RS-1048","Reyes Santos & Co., CPAs","10/31/2026","11/15/2026","Net 15","Oct 2026 retainer. CHECK: no EWT on invoice",[("Legal and professional fees","Bookkeeping & tax compliance retainer Oct 2026",25000),(IV,"Input VAT 12%",3000)],None),
 ("001190","Kusina ni Lola Restaurant","11/28/2026","11/28/2026","Due on receipt","Client lunch - Kalayaan Construction (6 pax)",[("Representation and entertainment","Client lunch",4200),(IV,"Input VAT 12%",504)],CASH),
 ("PB-44437","Petro Bayan Gas Station","12/04/2026","12/04/2026","Due on receipt","Diesel 50L - NBC 4521",[("Transportation and fuel","Diesel delivery truck",3125),(IV,"Input VAT 12%",375)],BANK),
 ("0538","Aling Nena's School & Office Supplies","10/22/2026","10/22/2026","Due on receipt","NON-VAT seller",[("Stationery and printing","Bond paper, ballpens, record book",1650)],CASH),
 ("OR-0659","QuickFix Aircon Services","12/18/2026","12/18/2026","Due on receipt","OFFICIAL RECEIPT, not a VAT invoice: input VAT 720 not claimed",[("Repairs and Maintenance","Aircon cleaning + freon recharge x2",6720)],BANK),
 ("8098","Golden Hardware Wholesale","12/25/2026","12/25/2026","Due on receipt","VAT MISMATCH: invoice VAT 2,600 vs 12% of 20,000 = 2,400",[("Purchases","Padlocks and door hinges for resale",20000),(IV,"Input VAT 12% (recomputed)",2400),("Suspense - for review","Excess VAT billed, confirm with supplier",200)],BANK),
 ("OR-7781904","City Government of Marikina","11/03/2026","11/03/2026","Due on receipt","AF51 OR 7781904",[("Taxes and licenses","Signage permit, building permit, documentary stamp",3500)],CASH),
 ("C-2026-1119-44812","Guangzhou Hengli Tools Mfg. Co., Ltd.","11/19/2026","11/19/2026","","Import entry C-2026-1119-44812, B/L COSU6612049981; supplier invoice not in pack",[("Purchases","Hand tools assorted 1,200 sets - FOB",176400)],None),
 ("BOC-0198832","Bureau of Customs","11/19/2026","11/19/2026","Due on receipt","Entry C-2026-1119-44812, BOC OR 0198832",[("Purchases","Customs duty 5%",9250),("Input VAT - Importation","Import VAT 12%",23520)],CASH),
 ("C-44812-FRT","R. Villanueva (Customs Broker)","11/19/2026","11/19/2026","","ASSUMED payee for freight/insurance + brokerage on entry C-2026-1119-44812",[("Purchases","Freight and insurance",8600),("Purchases","Brokerage, arrastre and other charges",1750)],None),
 ("0048029","Tindahan Mart Supermarket","10/06/2026","10/06/2026","Due on receipt","Office pantry. Receipt shows cash 2,000 / change -992.25",[("Supplies","Pantry supplies",2686.12),(IV,"Input VAT 12%",306.13)],CASH),
 ("221401235","Sulit-Stop Convenience Store","10/09/2026","10/09/2026","Due on receipt","No buyer name/TIN: input VAT 59.36 not claimed",[("Other general and administrative expenses","Water, sandwiches, coffee",554)],CASH),
 ("0012151","Botika ng Bayan Pharmacy","10/14/2026","10/14/2026","Due on receipt","First-aid supplies. Receipt shows cash 1,500 / change -470",[("Supplies","First aid, alcohol, paracetamol, masks",1799.64),(IV,"Input VAT 12%",170.36)],CASH),
 ("087-0034439","Pahina Bookstore","10/20/2026","10/20/2026","Due on receipt","",[("Stationery and printing","Bond paper, stapler, folders, ink, tape",5648.44),(IV,"Input VAT 12%",677.81)],CC),
 ("CK-019150","Kape Kanto Coffee","10/24/2026","10/24/2026","Due on receipt","Meeting w/ supplier (paid by card)",[("Representation and entertainment","Coffee meeting",1290.18),(IV,"Input VAT 12%",154.82)],CASH),
 ("0128-0442219","Manok House Fast Food","10/31/2026","10/31/2026","Due on receipt","Staff lunch - month-end inventory. Receipt shows cash 3,000 / change -1,319",[("Other general and administrative expenses","Staff meal",3856.25),(IV,"Input VAT 12%",462.75)],CASH),
 ("SG-2026-11-0091564","SakayGo Technologies Inc.","11/02/2026","11/02/2026","Due on receipt","Ride Marikina to Pasig",[("Transportation and fuel","Car ride + booking fee",380.36),(IV,"Input VAT 12%",45.64)],CASH),
 ("PG-034728","Park-N-Go Parking","11/02/2026","11/02/2026","Due on receipt","OFFICIAL RECEIPT, not a VAT invoice: input VAT 16.07 not claimed",[("Transportation and fuel","Parking 3h",150)],CASH),
 ("0052607","Tindahan Mart Supermarket","11/03/2026","11/03/2026","Due on receipt","Buyer block blank: input VAT 125.01 not claimed; rice/eggs, check if personal. Cash 3,000 / change -101.75",[("Supplies","Groceries",3101.75)],CASH),
 ("PB-45304","Petro Bayan Gas Station","11/09/2026","11/09/2026","Due on receipt","Diesel - NBC 4521, fleet card",[("Transportation and fuel","Diesel 48.52L",2722.75),(IV,"Input VAT 12%",326.73)],CASH),
 ("T3-88121248","Metro Expressway Toll Corp.","11/09/2026","11/09/2026","Due on receipt","RFID",[("Transportation and fuel","Class 2 toll",269.64),(IV,"Input VAT 12%",32.36)],CASH),
 ("PX-0045-77440","Padala Express Courier","11/11/2026","11/11/2026","Due on receipt","",[("Shipping and delivery expense","Courier Cebu/Davao",1214.29),(IV,"Input VAT 12%",145.71)],CASH),
 ("0729","Kidlat Printing & Xerox","11/14/2026","11/14/2026","Due on receipt","NON-VAT seller",[("Stationery and printing","Tarpaulin sale banners, photocopy, lamination",2076.50)],CASH),
 ("1504","Aqua Pure Water Refilling Station","11/18/2026","11/18/2026","Due on receipt","NON-VAT seller",[("Utilities","Water refill",270)],CASH),
 ("CH-0991361","Citimart Hardware & Home","11/21/2026","11/21/2026","Due on receipt","Store maintenance supplies",[("Repairs and Maintenance","Bulbs, extension cords, brooms, mop, padlocks",4244.64),(IV,"Input VAT 12%",509.36)],CASH),
 ("064-0083664","Mega Department Store","11/25/2026","11/25/2026","Due on receipt","Small store fixtures (debit card)",[("Supplies","Electric fans, wall clock, storage bins",5397.99),(IV,"Input VAT 12%",647.76)],CASH),
 ("CH-1129870","Citimart Hardware & Home","11/28/2026","11/28/2026","Due on receipt","Christmas store decorations",[("Other general and administrative expenses","Christmas lights, parol, garland",5133.93),(IV,"Input VAT 12%",616.07)],CASH),
 ("KG-01079","Kaldero Grill & Restaurant","12/05/2026","12/05/2026","Due on receipt","Dinner w/ Mabuhay Builders",[("Representation and entertainment","Client dinner",2452.23),(IV,"Input VAT 12%",294.27)],CC),
 ("PX-0045-91220","Padala Express Courier","12/10/2026","12/10/2026","Due on receipt","Holiday shipments",[("Shipping and delivery expense","Courier Iloilo/Baguio",3133.93),(IV,"Input VAT 12%",376.07)],CASH),
 ("0061504","Tindahan Mart Supermarket","12/12/2026","12/12/2026","Due on receipt","Office pantry. Receipt shows cash 2,000 / change -353",[("Supplies","Pantry supplies",2100.89),(IV,"Input VAT 12%",252.11)],CASH),
 ("0071420","Tindahan Mart Supermarket","12/14/2026","12/14/2026","Due on receipt","Christmas gifts for clients",[("Representation and entertainment","Gift baskets, ham, queso de bola, fruit cocktail",23207.14),(IV,"Input VAT 12%",2784.86)],CC),
 ("PB-45919","Petro Bayan Gas Station","12/19/2026","12/19/2026","Due on receipt","Diesel + engine oil - NBC 4521, fleet card",[("Transportation and fuel","Diesel 52.10L + engine oil",3301.91),(IV,"Input VAT 12%",396.23)],CASH),
 ("HC-1219","Handaan Catering Services Inc.","12/19/2026","12/19/2026","","Christmas party. Terms 50% DP, balance on event; no payment evidence",[("Other general and administrative expenses","Christmas party buffet 40 pax + venue/sound/host",34500),(IV,"Input VAT 12%",4140)],None),
 ("221402050","Sulit-Stop Convenience Store","12/22/2026","12/22/2026","Due on receipt","No buyer name/TIN: input VAT 1.61 not claimed",[("Utilities","Prepaid load 3x500 + bills payment fee",1515)],CASH),
 ("KG-01188","Kaldero Grill & Restaurant","12/22/2026","12/22/2026","Due on receipt","Year-end dinner w/ Kalayaan Construction",[("Representation and entertainment","Client dinner",2383.93),(IV,"Input VAT 12%",286.07)],CASH),
 ("CH-1004838","Citimart Hardware & Home","12/27/2026","12/27/2026","Due on receipt","Repainting supplies",[("Repairs and Maintenance","Paint rollers, masking tape, sandpaper",1262.50),(IV,"Input VAT 12%",151.50)],CASH),
 ("ACK-20261229","Mang Tomas Sari-Sari Store","12/29/2026","12/29/2026","Due on receipt","Acknowledgement receipt only, no TIN/serial: not a valid invoice",[("Other general and administrative expenses","Ice and softdrinks",680)],CASH),
 ("89904","Pacific Steel & Cement Supply Inc.","12/02/2026","01/01/2027","Net 30","Terms: 30 days PDC",[("Purchases","Cement, deformed bars, GI sheets for resale",235600),(IV,"Input VAT 12%",28272)],None),
]
rows=[]; totals={}
for no,sup,dt,due,terms,memo,lines,pay in bills:
    for acct,desc,amt in lines:
        rows.append([no,sup,dt,due,terms,memo,acct,desc,f"{amt:.2f}"])
    totals[no]=(sup,dt,round(sum(D(str(a)) for _,_,a in lines),2),pay)
w("05_bills.csv", ["Bill No","Supplier","Bill Date","Due Date","Terms","Memo","Account","Line Description","Line Amount"], rows)

# ---- Payment feeds (bank data import: Date, Description, Amount) ----
def feed(acct):
    return [[dt, f"{sup} {no}", f"-{amt}"] for no,(sup,dt,amt,pay) in totals.items() if pay==acct]
cash = feed(CASH)
cash += [["11/22/2026","Sales receipt 0007 Juan Dela Cruz","21616.00"],
         ["12/15/2026","Cash deposit - store sales to Pinoy Commerce Bank","-38450.00"],
         ["12/20/2026","Sales receipt 0009 San Roque Parish Church","42224.00"]]
w("06_feed_cash_on_hand.csv", ["Date","Description","Amount"], sorted(cash, key=lambda r:(r[0][6:],r[0])))
w("07_feed_credit_card.csv", ["Date","Description","Amount"], feed(CC))
bank = [["12/02/2026","Check #000818 - Sta. Elena Realty (Dec rent)","-32100.00"],
 ["12/04/2026","POS - Petro Bayan Gas Station","-3500.00"],
 ["12/11/2026","Deposit - Mabuhay Builders (partial SI 0008)","50000.00"],
 ["12/15/2026","Cash deposit - store sales","38450.00"],
 ["12/18/2026","Online transfer - QuickFix Aircon","-6720.00"],
 ["12/23/2026","Payroll credit - 4 employees","-105405.30"],
 ["12/25/2026","Check #000819 - Golden Hardware Wholesale","-22600.00"],
 ["12/31/2026","Service charge","-150.00"]]
w("08_feed_bank_dec.csv", ["Date","Description","Amount"], bank)
for no,(sup,dt,amt,pay) in totals.items(): print(f"{no:22} {sup[:30]:30} {dt} {amt:>12} {pay or 'UNPAID'}")
print("cash out", sum(D(r[2]) for r in cash))
