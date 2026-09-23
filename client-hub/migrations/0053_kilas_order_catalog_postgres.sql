CREATE TABLE IF NOT EXISTS kilas_order_catalog (
  id BIGSERIAL PRIMARY KEY,
  product_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  short_description TEXT NOT NULL,
  category TEXT NOT NULL,
  image_source_url TEXT NOT NULL,
  customer_price_idr INTEGER NOT NULL CHECK(customer_price_idr >= 0),
  source_platform TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_seller TEXT,
  source_price_idr INTEGER NOT NULL CHECK(source_price_idr >= 0),
  estimated_shipping_idr INTEGER NOT NULL DEFAULT 0 CHECK(estimated_shipping_idr >= 0),
  estimated_fee_idr INTEGER NOT NULL DEFAULT 0 CHECK(estimated_fee_idr >= 0),
  service_fee_idr INTEGER NOT NULL DEFAULT 0 CHECK(service_fee_idr >= 0),
  CHECK(customer_price_idr = source_price_idr + estimated_shipping_idr + estimated_fee_idr + service_fee_idr),
  availability_status TEXT NOT NULL DEFAULT 'CHECK_REQUIRED' CHECK(availability_status IN ('AVAILABLE','CHECK_REQUIRED','PAUSED')),
  source_checked_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kilas_order_catalog_active_sort ON kilas_order_catalog(is_active,sort_order);
INSERT INTO kilas_order_catalog
(product_code,name,short_description,category,image_source_url,customer_price_idr,source_platform,source_url,source_seller,source_price_idr,estimated_shipping_idr,estimated_fee_idr,service_fee_idr,availability_status,source_checked_at,is_active,sort_order,created_at,updated_at)
VALUES
('KIL-P-1001','ANTARESTAR Cartenz Daypack','Ransel travel ringan dengan kompartemen utama lega, strap nyaman, dan desain outdoor untuk perjalanan harian.','Travel','https://down-id.img.susercontent.com/file/id-11134207-822wm-ml8kevhihclka7',199000,'Shopee','https://shopee.co.id/ANTARESTAR-Official-Daypack-Cartenz-Tas-Ransel-Gunung-Outdoor-Travel-Backpack-Terbaru-Daypack-Tas-Lebaran-Tas-Mudik-i.561861137.11083830926','Antarestar Official Shop',150000,18000,6000,25000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1002','AstarFlask Tumbler 1L','Tumbler stainless berkapasitas besar dengan insulasi vakum untuk minuman panas atau dingin saat bepergian.','Lifestyle','https://down-id.img.susercontent.com/file/id-11134207-8224z-ml4pm0bskumlef',169000,'Shopee','https://shopee.co.id/AstarFlask-official-Store-Original-Tumbler-Stainless-Tumbler-Tahan-Panas-Dingin-Botol-Minum-1-Liter-Anak-Laki-Laki-Botol-Air-Minum-Besar-Premium-Quality-i.1640873588.50055162995','AstarFlasK Official Store',125000,15000,5000,24000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,2,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1003','BASIKE Powerbank 10000mAh','Powerbank ringkas dengan indikator daya, beberapa output, dan kabel bawaan untuk kebutuhan harian dan perjalanan.','Gadget','https://down-id.img.susercontent.com/file/id-11134207-81ztd-mdwwj6zl1r0h7f',199000,'Shopee','https://shopee.co.id/BASIKE-Powerbank-10000-mAh-Fast-Charging-Dual-USB-LCD-build-in-Cables-Power-Bank-Mini-Murah-Ori-Lucu-i.227057943.6835278085','Basike Official Shop',149000,12000,5000,33000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,3,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1004','UGREEN Travel Organizer Pouch','Pouch organizer kompak untuk charger, kabel, earphone, flashdisk, dan aksesori kecil agar tetap rapi saat bepergian.','Gadget','https://down-id.img.susercontent.com/file/id-11134207-7qukw-lfj6f1txkvp634',129000,'Shopee','https://shopee.co.id/UGREEN-ORIGINAL-Handbag-Storage-Pouch-Bag-Case-Organizer-Black-Eva-Tempat-Headset-Earphone-Kabel-Charger-Flashdisk-Waterproof-Leather-Tas-Clutch-ORI-i.219626971.20478444191','Base On User Indonesia',85000,15000,4000,25000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,4,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1005','GOTO Digital Luggage Scale 50kg','Timbangan koper digital portabel untuk mengecek berat bagasi sebelum berangkat dan membantu menghindari kelebihan bagasi.','Travel','https://down-id.img.susercontent.com/file/2f0178551d3ddadb438aafb95a3489f4',100000,'Shopee','https://shopee.co.id/Goto-Timbangan-Koper-Tas-Digital-Luggage-Scale-Bagasi-Gantung-Travel-50-Kg-i.216921952.7832746847','GOTO Authorized Store',64710,15000,3290,17000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,5,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1006','Rhodey Memory Foam Neck Pillow','Bantal leher memory foam berbentuk U dengan permukaan lembut untuk perjalanan pesawat, kereta, atau mobil.','Travel','https://down-id.img.susercontent.com/file/id-11134207-7r98u-loum72sk0vho9d',90000,'Shopee','https://shopee.co.id/Rhodey-MEMORY-FOAM-U-shaped-Bantal-Leher-Travel-Neck-Pillow-Empuk-Beludru-Travelling-i.6043620.24452562370','rkaseshop',54500,18000,2500,15000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,6,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1007','Tweezy Gadget Organizer','Organizer tahan percikan dengan banyak slot untuk kabel, charger, powerbank, kartu memori, dan aksesori perjalanan.','Gadget','https://down-id.img.susercontent.com/file/id-11134207-7ra0o-mbrmkmffudes31',80000,'Shopee','https://shopee.co.id/Tas-Gadget-Organizer-Pouch-Canvas-Waterproof-With-Many-Slot-Penyimpanan-Serba-Guna-Kabel-HP-Travel-i.1106253560.24654449928','Tweezy Official Store',45599,15000,3401,16000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1008','MIISOO Foldable Travel Bag','Tas travel lipat ringan yang bisa dipasang di handle koper dan dilipat kembali saat tidak digunakan.','Travel','https://down-id.img.susercontent.com/file/id-11134207-7qul9-lk9dzfif3atw1d',75000,'Shopee','https://shopee.co.id/MIISOO-Foldable-Travel-Bag-Tas-Koper-Luggage-Tas-Travel-Tas-Hand-Carry-i.294096817.22850202795','Miisoo Official Shop',39900,15000,4100,16000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,8,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1009','Bluetooth Selfie Tripod 170cm','Selfie stick sekaligus tripod hingga sekitar 170 cm dengan remote Bluetooth untuk foto grup, video, dan konten perjalanan.','Gadget','https://down-id.img.susercontent.com/file/sg-11134201-7rd5l-lx1160gy5g7c71',139000,'Shopee','https://shopee.co.id/Bluetooth-Selfie-Stick-Tripod-Dengan-Remote-Control-1.7-M-Bluetooth-Selfie-Stick-Wireless-Monopod-Tripod-Multifungsi-Tripod-Dengan-Remote-Control-Panjang-Ponsel-Tripod-Tripod-Handphone-Nirkabel-Handheld-Dapat-Diperpanjang-Selfie-Stick-170CM-i.981724774.19790651461','TopRace Star',91000,18000,5000,25000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,9,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
('KIL-P-1010','Payung Lipat Otomatis Anti-UV','Payung lipat otomatis yang ringkas untuk hujan dan aktivitas luar ruang, mudah disimpan di tas harian atau koper.','Lifestyle','https://down-id.img.susercontent.com/file/id-11134207-822wl-mlj2q5cru9sfe2',60000,'Shopee','https://shopee.co.id/Satu-Keluarga-Payung-Lipat-Otomatis-Buka-Tutup-Lipat-Anti-UV-C432-Payung-UV-Nivil-Perlindungan-Matahari-Payung-Hujan-Anti-Sinar-Matahari-UV-i.494896079.17189627222','Satu Keluarga Official Shop',30911,14000,2089,13000,'CHECK_REQUIRED',CURRENT_TIMESTAMP,TRUE,10,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
ON CONFLICT(product_code) DO UPDATE SET
name=excluded.name,short_description=excluded.short_description,category=excluded.category,image_source_url=excluded.image_source_url,
customer_price_idr=excluded.customer_price_idr,source_platform=excluded.source_platform,source_url=excluded.source_url,source_seller=excluded.source_seller,
source_price_idr=excluded.source_price_idr,estimated_shipping_idr=excluded.estimated_shipping_idr,estimated_fee_idr=excluded.estimated_fee_idr,
service_fee_idr=excluded.service_fee_idr,availability_status=excluded.availability_status,source_checked_at=excluded.source_checked_at,
is_active=excluded.is_active,sort_order=excluded.sort_order,updated_at=CURRENT_TIMESTAMP;