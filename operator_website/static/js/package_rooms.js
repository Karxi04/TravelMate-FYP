/* Read-only provider metadata helps describe a promise; it never reserves a room. */
function TravelMateRoomPicker(doc, savedRoom, onChange) {
  const select = doc.getElementById('providerRoom');
  const field = doc.getElementById('roomType');
  const status = doc.getElementById('providerRoomStatus');
  const details = doc.getElementById('providerRoomDetails');
  const action = doc.getElementById('roomSelectionAction');
  const roomId = doc.getElementById('roomSelectionId');
  const hotelId = doc.getElementById('roomHotelId');
  let hotel = null;
  let rooms = [];
  let selected = savedRoom;
  function describe(room) {
    const parts = [room.roomName];
    const beds = (room.bedTypes || []).map(b => `${b.quantity != null ? b.quantity + ' × ' : ''}${b.bedType}`);
    if (beds.length) parts.push(`Bed details${room.bedRelation ? ' (' + room.bedRelation + ')' : ''}: ${beds.join('; ')}`);
    if (room.maxOccupancy != null) parts.push(`Maximum ${room.maxOccupancy} guests`);
    if (room.maxAdults != null) parts.push(`Maximum ${room.maxAdults} adults`);
    if (room.maxChildren != null) parts.push(`Maximum ${room.maxChildren} children`);
    return parts.join(' · ');
  }
  function showDetails(room) {
    details.textContent = room ? [describe(room), room.description, (room.roomAmenities || []).join(', ')].filter(Boolean).join(' — ') : '';
  }
  select.addEventListener('change', () => {
    selected = rooms.find(room => room.id === select.value) || null;
    action.value = selected ? 'select' : 'clear';
    roomId.value = selected ? selected.id : '';
    hotelId.value = selected ? hotel.hotelId : '';
    if (selected) field.value = describe(selected);
    showDetails(selected);
    onChange();
  });
  return {setHotel(value, reset) {
    if (reset) {
      if (selected) field.value = '';
      selected = null;
      action.value = 'clear';
      roomId.value = hotelId.value = '';
    }
    hotel = value;
    rooms = Array.isArray(hotel?.rooms) ? hotel.rooms : [];
    if (selected && selected.hotelId === hotel?.hotelId && !rooms.some(room => room.id === selected.id)) rooms = [...rooms, selected];
    select.replaceChildren();
    const manual = doc.createElement('option');
    manual.value = ''; manual.textContent = 'Manual / entire-property configuration';
    select.appendChild(manual);
    for (const room of rooms) {
      const option = doc.createElement('option');
      option.value = room.id; option.textContent = room.roomName;
      select.appendChild(option);
    }
    select.value = selected?.id || '';
    status.textContent = rooms.length
      ? 'Room metadata only. Review the intended configuration below; availability and reservations are not confirmed.'
      : hotel ? 'Room details unavailable from provider; specify the accommodation offered.'
        : 'Select a property for provider room details, or describe a manual / entire-property configuration.';
    showDetails(selected);
  }};
}
if (typeof module !== 'undefined') module.exports = TravelMateRoomPicker;
