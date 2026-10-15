-- ==============================================================================
-- HOTEL BOOKING SYSTEM (SUPABASE POSTGRESQL SCHEMA)
-- 10 Physical Rooms across 4 Categories with Availability Tracking
-- ==============================================================================

-- 1. Create table: room_types
create table if not exists room_types (
  id text primary key,
  name text not null,
  capacity integer not null,
  price_per_night numeric not null,
  description text,
  image_url text
);

-- Seed room_types
insert into room_types (id, name, capacity, price_per_night, description, image_url) values
('standard', 'Standard Deluxe Room', 2, 1200, 'ห้องพักสไตล์โมเดิร์น เตียงคิงไซส์ พร้อมสิ่งอำนวยความสะดวกครบครัน Wi-Fi ฟรี และสมาร์ททีวี', 'https://images.unsplash.com/photo-1611892440504-42a792e24d32?auto=format&fit=crop&w=1200&q=80'),
('executive', 'Executive Suite', 2, 2500, 'ห้องสวีทสุดหรู วิวเมืองแบบพาโนรามา มีอ่างอาบน้ำจากุซซี่ ระเบียงส่วนตัว และฟรีอาหารเช้า', 'https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?auto=format&fit=crop&w=1200&q=80'),
('family', 'Family Grand Suite', 4, 3800, 'ห้องพักครอบครัวขนาดใหญ่ 2 ห้องนอน 2 ห้องน้ำ ห้องนั่งเล่นกว้างขวาง เหมาะสำหรับการพักผ่อนแบบครอบครัว', 'https://images.unsplash.com/photo-1591088398332-8a7791972843?auto=format&fit=crop&w=1200&q=80'),
('penthouse', 'Presidential Penthouse', 6, 6500, 'เพนต์เฮาส์ชั้นบนสุด สระว่ายน้ำส่วนตัว บัตเลอร์บริการ 24 ชั่วโมง วิวเส้นขอบฟ้าใจกลางเมืองแบบ 360 องศา', 'https://images.unsplash.com/photo-1631049307264-da0ec9d70304?auto=format&fit=crop&w=1200&q=80')
on conflict (id) do update set
  name = excluded.name,
  capacity = excluded.capacity,
  price_per_night = excluded.price_per_night,
  description = excluded.description,
  image_url = excluded.image_url;

-- 2. Create table: rooms (10 Physical Room Instances)
create table if not exists rooms (
  room_number text primary key,
  room_type_id text references room_types(id) on delete cascade,
  floor integer not null,
  status text default 'operational'
);

-- Seed 10 physical rooms
insert into rooms (room_number, room_type_id, floor, status) values
('101', 'standard', 1, 'operational'),
('102', 'standard', 1, 'operational'),
('103', 'standard', 1, 'operational'),
('104', 'standard', 1, 'operational'),
('201', 'executive', 2, 'operational'),
('202', 'executive', 2, 'operational'),
('203', 'executive', 2, 'operational'),
('301', 'family', 3, 'operational'),
('302', 'family', 3, 'operational'),
('401', 'penthouse', 4, 'operational')
on conflict (room_number) do update set
  room_type_id = excluded.room_type_id,
  floor = excluded.floor,
  status = excluded.status;

-- 3. Create table: users
create table if not exists users (
  phone text primary key,
  pin text not null,
  name text not null,
  role text default 'user',
  created_at timestamptz default timezone('utc'::text, now())
);

-- Seed default admin account
insert into users (phone, pin, name, role) values
('0800000000', '9999', 'Hotel Admin Officer', 'admin')
on conflict (phone) do nothing;

-- 4. Create table: bookings
create table if not exists bookings (
  booking_id text primary key,
  room_number text references rooms(room_number) on delete set null,
  room_type_id text references room_types(id) on delete set null,
  guest_phone text not null,
  guest_name text not null,
  check_in date not null,
  check_out date not null,
  total_nights integer not null,
  total_price numeric not null,
  status text default 'Confirmed',
  channel text default 'web',
  created_at timestamptz default timezone('utc'::text, now())
);

-- Enable Row Level Security (RLS) & Public Policies for Direct API Access
alter table room_types enable row level security;
alter table rooms enable row level security;
alter table users enable row level security;
alter table bookings enable row level security;

create policy "Public can read room_types" on room_types for select using (true);
create policy "Public can read rooms" on rooms for select using (true);
create policy "Public can read and write users" on users for all using (true);
create policy "Public can read and write bookings" on bookings for all using (true);
