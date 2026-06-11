-- str-agent schema + demo properties.
-- Apply with: psql "$DATABASE_URL" -f schema.sql
-- Bookings are seeded separately (seed.py) so check-in dates stay relative to today.

CREATE TABLE properties (
  name TEXT PRIMARY KEY,
  check_in_time TEXT, check_out_time TEXT,
  wifi_name TEXT, wifi_password TEXT,
  parking_info TEXT, pet_policy TEXT, amenities TEXT, supply_policy TEXT,
  door_code TEXT, building_code TEXT
);

CREATE TABLE bookings (
  booking_id TEXT PRIMARY KEY,
  guest_last_name TEXT NOT NULL,
  property_name TEXT NOT NULL REFERENCES properties(name),
  check_in_date DATE NOT NULL, check_out_date DATE NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE agent_log (
  id SERIAL PRIMARY KEY, ts TIMESTAMP NOT NULL DEFAULT now(),
  guest_message TEXT NOT NULL, intent TEXT, should_escalate BOOLEAN,
  draft_response TEXT, tools_used TEXT, iterations INTEGER, codes_released BOOLEAN
);

CREATE TABLE conversations (
  id SERIAL PRIMARY KEY,
  conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
  ts TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversations_id_ts ON conversations (conversation_id, ts);

INSERT INTO properties VALUES
('Pelican Beach 1006', '4:00 PM', '10:00 AM', 'Pelican-Guest-1006', 'Sunset2024',
 'Garage level P2, spot 1006. One pass per unit included.',
 'No pets. Service animals only with documentation.',
 'Full kitchen with washer/dryer, coffee maker, beach chairs, gulf-front balcony, sleeps 6 (king, queen, queen pull-out).',
 'Starter supplies only (toilet paper, paper towels, soap). No mid-stay restocking. Nearest store: Publix at Destin Commons, 10 min drive.',
 '4218', '9135'),
('Pelican Beach 707', '4:00 PM', '10:00 AM', 'Pelican-Guest-707', 'Sunset2024',
 'Garage level P1, spot 707. One pass per unit included.',
 'Small dogs under 25 lbs welcome with $150 non-refundable pet fee. Max 1 dog.',
 'Full kitchen with washer/dryer, coffee maker, beach chairs, gulf-front balcony, sleeps 4 (king, queen).',
 'Starter supplies only. No mid-stay restocking. Nearest store: Publix at Destin Commons, 10 min drive.',
 '7707', '9135'),
('Okaloosa 3BR', '4:00 PM', '10:00 AM', 'OkaloosaWiFi', 'Beach2024',
 'Driveway parking for 2 cars.', 'No pets.',
 '3 bedrooms, full kitchen, washer/dryer.', 'Starter supplies only.',
 '3301', NULL);
