class_name Modbus
extends RefCounted
## Modbus TCP framing and the four function codes the plant needs.
##
## Pure functions over bytes, so the codec is tested without sockets. A bit
## image is a PackedByteArray holding one 0/1 value per bit (not packed).
## Frame layout (MBAP header + PDU): transaction id u16, protocol id u16 (0),
## length u16 (unit id + PDU bytes), unit id u8, then the PDU.

const FC_READ_COILS: int = 1
const FC_READ_DISCRETE_INPUTS: int = 2
const FC_WRITE_SINGLE_COIL: int = 5
const FC_WRITE_MULTIPLE_COILS: int = 15

const EX_ILLEGAL_FUNCTION: int = 1
const EX_ILLEGAL_ADDRESS: int = 2
const EX_ILLEGAL_VALUE: int = 3

const HEADER_BYTES: int = 7
const COIL_ON: int = 0xFF00


## `count` zero bytes (resize() reports an error code strict mode won't drop).
static func zeros(count: int) -> PackedByteArray:
	var out: PackedByteArray = PackedByteArray()
	if out.resize(count) != OK:
		push_error("cannot allocate %d bytes" % count)
	out.fill(0)
	return out


static func u16(value: int) -> PackedByteArray:
	return PackedByteArray([(value >> 8) & 0xFF, value & 0xFF])


static func read_u16(data: PackedByteArray, at: int) -> int:
	return (data[at] << 8) | data[at + 1]


static func frame(transaction: int, unit: int, pdu: PackedByteArray) -> PackedByteArray:
	var out: PackedByteArray = u16(transaction)
	out.append_array(u16(0))
	out.append_array(u16(pdu.size() + 1))
	out.append_array(PackedByteArray([unit & 0xFF]))
	out.append_array(pdu)
	return out


## Bytes the first frame in `buffer` occupies, or 0 while it is incomplete.
static func frame_size(buffer: PackedByteArray) -> int:
	if buffer.size() < HEADER_BYTES:
		return 0
	var total: int = 6 + read_u16(buffer, 4)
	return total if buffer.size() >= total else 0


static func transaction_of(frame_bytes: PackedByteArray) -> int:
	return read_u16(frame_bytes, 0)


static func pdu_of(frame_bytes: PackedByteArray) -> PackedByteArray:
	return frame_bytes.slice(HEADER_BYTES)


static func pack_bits(bits: PackedByteArray) -> PackedByteArray:
	var out: PackedByteArray = zeros((bits.size() + 7) / 8)
	for i: int in range(bits.size()):
		if bits[i] != 0:
			out[i / 8] |= 1 << (i % 8)
	return out


static func unpack_bits(data: PackedByteArray, count: int) -> PackedByteArray:
	var out: PackedByteArray = zeros(count)
	for i: int in range(count):
		out[i] = (data[i / 8] >> (i % 8)) & 1
	return out


static func read_request(function: int, address: int, count: int) -> PackedByteArray:
	var out: PackedByteArray = PackedByteArray([function])
	out.append_array(u16(address))
	out.append_array(u16(count))
	return out


static func write_coils_request(address: int, bits: PackedByteArray) -> PackedByteArray:
	var packed: PackedByteArray = pack_bits(bits)
	var out: PackedByteArray = PackedByteArray([FC_WRITE_MULTIPLE_COILS])
	out.append_array(u16(address))
	out.append_array(u16(bits.size()))
	out.append_array(PackedByteArray([packed.size()]))
	out.append_array(packed)
	return out


static func exception(function: int, code: int) -> PackedByteArray:
	return PackedByteArray([function | 0x80, code])


## Bits from a read response, or an empty array for an exception or a short PDU.
static func read_response_bits(pdu: PackedByteArray, count: int) -> PackedByteArray:
	if pdu.size() < 2 or pdu[0] & 0x80 != 0 or pdu.size() < 2 + pdu[1]:
		return PackedByteArray()
	if pdu[1] * 8 < count:
		return PackedByteArray()
	return unpack_bits(pdu.slice(2), count)


## Answer one request PDU against the plant's bit images. Writes land in
## `coils` in place; discrete inputs are read-only, as in the protocol.
static func serve(
	pdu: PackedByteArray, coils: PackedByteArray, inputs: PackedByteArray
) -> PackedByteArray:
	if pdu.size() < 5:
		return exception(pdu[0] if pdu.size() > 0 else 0, EX_ILLEGAL_VALUE)
	var function: int = pdu[0]
	var address: int = read_u16(pdu, 1)
	var value: int = read_u16(pdu, 3)
	match function:
		FC_READ_COILS:
			return _serve_read(function, address, value, coils)
		FC_READ_DISCRETE_INPUTS:
			return _serve_read(function, address, value, inputs)
		FC_WRITE_SINGLE_COIL:
			return _serve_write_single(pdu, address, value, coils)
		FC_WRITE_MULTIPLE_COILS:
			return _serve_write_multiple(pdu, address, value, coils)
	return exception(function, EX_ILLEGAL_FUNCTION)


static func _serve_read(
	function: int, address: int, count: int, image: PackedByteArray
) -> PackedByteArray:
	if count < 1 or count > 2000:
		return exception(function, EX_ILLEGAL_VALUE)
	if address + count > image.size():
		return exception(function, EX_ILLEGAL_ADDRESS)
	var packed: PackedByteArray = pack_bits(image.slice(address, address + count))
	var out: PackedByteArray = PackedByteArray([function, packed.size()])
	out.append_array(packed)
	return out


static func _serve_write_single(
	pdu: PackedByteArray, address: int, value: int, coils: PackedByteArray
) -> PackedByteArray:
	if value != COIL_ON and value != 0:
		return exception(FC_WRITE_SINGLE_COIL, EX_ILLEGAL_VALUE)
	if address >= coils.size():
		return exception(FC_WRITE_SINGLE_COIL, EX_ILLEGAL_ADDRESS)
	coils[address] = 1 if value == COIL_ON else 0
	return pdu.slice(0, 5)


static func _serve_write_multiple(
	pdu: PackedByteArray, address: int, count: int, coils: PackedByteArray
) -> PackedByteArray:
	if count < 1 or pdu.size() < 6 or pdu.size() < 6 + pdu[5] or pdu[5] * 8 < count:
		return exception(FC_WRITE_MULTIPLE_COILS, EX_ILLEGAL_VALUE)
	if address + count > coils.size():
		return exception(FC_WRITE_MULTIPLE_COILS, EX_ILLEGAL_ADDRESS)
	var bits: PackedByteArray = unpack_bits(pdu.slice(6), count)
	for i: int in range(count):
		coils[address + i] = bits[i]
	return pdu.slice(0, 5)
