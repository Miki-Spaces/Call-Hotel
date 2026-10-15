-- Run this file in Supabase Dashboard > SQL Editor AFTER running schema.sql.
-- These functions keep room assignment and booking creation inside one DB transaction.

create or replace function public.create_hotel_booking(
  p_room_type_id text,
  p_guest_phone text,
  p_guest_name text,
  p_check_in date,
  p_check_out date,
  p_channel text default 'voicebot'
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $function$
declare
  v_room_number text;
  v_price_per_night numeric;
  v_total_nights integer;
  v_total_price numeric;
  v_booking_id text;
begin
  if p_check_in is null or p_check_out is null or p_check_out <= p_check_in then
    raise exception using errcode = '22023', message = 'INVALID_DATE_RANGE';
  end if;

  if nullif(trim(coalesce(p_guest_name, '')), '') is null then
    raise exception using errcode = '22023', message = 'GUEST_NAME_REQUIRED';
  end if;

  if nullif(trim(coalesce(p_guest_phone, '')), '') is null then
    raise exception using errcode = '22023', message = 'GUEST_PHONE_REQUIRED';
  end if;

  select rt.price_per_night
    into v_price_per_night
  from public.room_types rt
  where rt.id = p_room_type_id;

  if not found then
    raise exception using errcode = '22023', message = 'ROOM_TYPE_NOT_FOUND';
  end if;

  -- Lock this room type's physical room rows in a stable order.
  -- This serializes bookings for the same category so overlapping requests
  -- cannot assign the same physical room at the same time.
  perform 1
  from public.rooms r
  where r.room_type_id = p_room_type_id
    and r.status = 'operational'
  order by r.room_number
  for update;

  -- A booking overlaps when existing check-in < new check-out
  -- AND existing check-out > new check-in. Checkout day is not an occupied night.
  select r.room_number
    into v_room_number
  from public.rooms r
  where r.room_type_id = p_room_type_id
    and r.status = 'operational'
    and not exists (
      select 1
      from public.bookings b
      where b.room_number = r.room_number
        and b.status = 'Confirmed'
        and b.check_in < p_check_out
        and b.check_out > p_check_in
    )
  order by r.room_number
  limit 1;

  if v_room_number is null then
    raise exception using errcode = 'P0001', message = 'NO_ROOM_AVAILABLE';
  end if;

  v_total_nights := p_check_out - p_check_in;
  v_total_price := v_price_per_night * v_total_nights;
  v_booking_id := 'BK-' || upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10));

  insert into public.bookings (
    booking_id,
    room_number,
    room_type_id,
    guest_phone,
    guest_name,
    check_in,
    check_out,
    total_nights,
    total_price,
    status,
    channel
  ) values (
    v_booking_id,
    v_room_number,
    p_room_type_id,
    trim(p_guest_phone),
    trim(p_guest_name),
    p_check_in,
    p_check_out,
    v_total_nights,
    v_total_price,
    'Confirmed',
    coalesce(nullif(trim(p_channel), ''), 'voicebot')
  );

  return jsonb_build_object(
    'booking_id', v_booking_id,
    'room_number', v_room_number,
    'room_type_id', p_room_type_id,
    'guest_name', trim(p_guest_name),
    'guest_phone', trim(p_guest_phone),
    'check_in', p_check_in,
    'check_out', p_check_out,
    'total_nights', v_total_nights,
    'price_per_night', v_price_per_night,
    'total_price', v_total_price,
    'status', 'Confirmed',
    'channel', coalesce(nullif(trim(p_channel), ''), 'voicebot')
  );
end;
$function$;

create or replace function public.cancel_hotel_booking(
  p_booking_id text,
  p_guest_phone text
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $function$
declare
  v_booking_id text;
  v_room_number text;
  v_status text;
begin
  update public.bookings b
  set status = 'Cancelled'
  where b.booking_id = p_booking_id
    and b.guest_phone = trim(p_guest_phone)
    and b.status = 'Confirmed'
    and b.check_out > current_date
  returning b.booking_id, b.room_number, b.status
    into v_booking_id, v_room_number, v_status;

  if not found then
    -- Same response for a wrong phone, unknown ID, already-cancelled booking,
    -- or booking that has already ended.
    raise exception using errcode = 'P0001', message = 'BOOKING_NOT_FOUND_OR_NOT_CANCELLABLE';
  end if;

  return jsonb_build_object(
    'booking_id', v_booking_id,
    'room_number', v_room_number,
    'status', v_status,
    'message', 'Booking cancelled successfully'
  );
end;
$function$;

-- Restrict execution of the custom write functions to the server role.
grant execute on function public.create_hotel_booking(text, text, text, date, date, text) to service_role;
grant execute on function public.cancel_hotel_booking(text, text) to service_role;
