const {test} = require('node:test');
const assert = require('node:assert/strict');
const mount = require('../static/js/package_rooms');

function setup(saved = null) {
  const elements = {};
  function element() {
    return {value: '', textContent: '', children: [], listeners: {},
      addEventListener(event, callback) { this.listeners[event] = callback; },
      replaceChildren() { this.children = []; }, appendChild(node) { this.children.push(node); }};
  }
  const doc = {getElementById(id) { return elements[id] ||= element(); }, createElement: element};
  let changes = 0;
  const picker = mount(doc, saved, () => changes++);
  return {picker, elements, changes: () => changes, choose(id) {
    elements.providerRoom.value = id;
    elements.providerRoom.listeners.change();
  }};
}
const room = {id:'123',hotelId:'hotel-one',roomName:'Studio King',maxOccupancy:3,
  maxAdults:2,maxChildren:2,bedTypes:[{bedType:'King',quantity:1},{bedType:'Twin',quantity:2}],bedRelation:'OR',
  description:'Provider description',roomAmenities:['Wi-Fi']};

test('property selection does not select or reserve a room; choosing a room submits only identity', () => {
  const ui = setup();
  ui.picker.setHotel({hotelId:'hotel-one',rooms:[room]},true);
  assert.equal(ui.elements.roomType.value,'');
  assert.equal(ui.elements.providerRoom.value,'');
  assert.equal(ui.elements.roomSelectionAction.value,'clear');
  ui.choose('123');
  assert.equal(ui.elements.roomSelectionAction.value,'select');
  assert.equal(ui.elements.roomSelectionId.value,'123');
  assert.equal(ui.elements.roomHotelId.value,'hotel-one');
  assert.match(ui.elements.roomType.value,/Studio King.*Bed details \(OR\).*Maximum 3 guests/);
  assert.match(ui.elements.providerRoomDetails.textContent,/Provider description.*Wi-Fi/);
  assert.match(ui.elements.providerRoomStatus.textContent,/reservations are not confirmed/);
  assert.equal(ui.changes(),1);
});

test('unmapped rooms keep manual and entire-property configuration', () => {
  const ui = setup();
  ui.elements.roomType.value = 'Entire house: 3 bedrooms';
  ui.picker.setHotel({hotelId:'hotel-one'},true);
  assert.match(ui.elements.providerRoomStatus.textContent,/Room details unavailable/);
  assert.equal(ui.elements.roomType.value,'Entire house: 3 bedrooms');
  ui.choose('');
  assert.equal(ui.elements.roomSelectionAction.value,'clear');
  assert.equal(ui.elements.roomType.value,'Entire house: 3 bedrooms');
});

test('reopen preserves selected identity and operator configuration without an automatic save', () => {
  const ui = setup(room);
  ui.elements.roomType.value = 'Operator-confirmed studio layout';
  ui.picker.setHotel({hotelId:'hotel-one',rooms:[room]},false);
  assert.equal(ui.elements.providerRoom.value,'123');
  assert.equal(ui.elements.roomType.value,'Operator-confirmed studio layout');
  assert.equal(ui.elements.roomSelectionAction.value,'');
  assert.equal(ui.changes(),0);
});

test('hotel replacement and detach invalidate the previous source room', () => {
  const ui = setup(room);
  ui.elements.roomType.value='Studio King';
  ui.picker.setHotel({hotelId:'hotel-two',rooms:[]},true);
  assert.equal(ui.elements.roomType.value,'');
  assert.equal(ui.elements.roomSelectionId.value,'');
  assert.equal(ui.elements.providerRoom.children.length,1);
  assert.equal(ui.elements.roomSelectionAction.value,'clear');
  ui.picker.setHotel(null,true);
  assert.match(ui.elements.providerRoomStatus.textContent,/entire-property/);
});

test('switching to manual keeps reviewed text and removes the provider-room pointer', () => {
  const ui = setup();
  ui.picker.setHotel({hotelId:'hotel-one',rooms:[room]},true);
  ui.choose('123');
  const description = ui.elements.roomType.value;
  ui.choose('');
  assert.equal(ui.elements.roomType.value,description);
  assert.equal(ui.elements.roomSelectionAction.value,'clear');
  assert.equal(ui.elements.roomSelectionId.value,'');
  assert.equal(ui.elements.roomHotelId.value,'');
});
