extends GutTest
## The Modbus codec: framing, the four served function codes, exceptions.


func _coils() -> PackedByteArray:
	return PackedByteArray([1, 0, 1, 1, 0])


func _inputs() -> PackedByteArray:
	return PackedByteArray([0, 1, 1, 0, 0, 0, 0, 0, 1, 1])


func test_frame_has_mbap_header_then_pdu() -> void:
	var pdu: PackedByteArray = Modbus.read_request(Modbus.FC_READ_COILS, 0, 5)
	var got: PackedByteArray = Modbus.frame(0x1234, 1, pdu)
	assert_eq(got, PackedByteArray([0x12, 0x34, 0, 0, 0, 6, 1, 1, 0, 0, 0, 5]))
	assert_eq(Modbus.transaction_of(got), 0x1234)
	assert_eq(Modbus.pdu_of(got), pdu)


func test_frame_size_waits_for_a_whole_frame() -> void:
	var whole: PackedByteArray = Modbus.frame(7, 1, PackedByteArray([1, 0, 0, 0, 5]))
	assert_eq(Modbus.frame_size(whole.slice(0, 6)), 0, "header incomplete")
	assert_eq(Modbus.frame_size(whole.slice(0, 10)), 0, "pdu incomplete")
	assert_eq(Modbus.frame_size(whole), whole.size())
	var two: PackedByteArray = whole.duplicate()
	two.append_array(whole)
	assert_eq(Modbus.frame_size(two), whole.size(), "first of two frames")


func test_pack_and_unpack_bits_round_trip() -> void:
	var bits: PackedByteArray = PackedByteArray([1, 0, 0, 0, 0, 0, 0, 0, 1, 1])
	var packed: PackedByteArray = Modbus.pack_bits(bits)
	assert_eq(packed, PackedByteArray([0x01, 0x03]), "LSB first, as in Modbus")
	assert_eq(Modbus.unpack_bits(packed, bits.size()), bits)


func test_fc1_reads_coils() -> void:
	var reply: PackedByteArray = Modbus.serve(
		Modbus.read_request(Modbus.FC_READ_COILS, 0, 5), _coils(), _inputs()
	)
	assert_eq(reply, PackedByteArray([Modbus.FC_READ_COILS, 1, 0b01101]))
	assert_eq(Modbus.read_response_bits(reply, 5), _coils())


func test_fc2_reads_discrete_inputs_from_an_offset() -> void:
	var reply: PackedByteArray = Modbus.serve(
		Modbus.read_request(Modbus.FC_READ_DISCRETE_INPUTS, 1, 9), _coils(), _inputs()
	)
	assert_eq(Modbus.read_response_bits(reply, 9), _inputs().slice(1))


func test_fc5_writes_one_coil_and_echoes() -> void:
	var coils: PackedByteArray = _coils()
	var on: PackedByteArray = PackedByteArray([Modbus.FC_WRITE_SINGLE_COIL, 0, 1, 0xFF, 0x00])
	assert_eq(Modbus.serve(on, coils, _inputs()), on)
	assert_eq(coils[1], 1)
	var off: PackedByteArray = PackedByteArray([Modbus.FC_WRITE_SINGLE_COIL, 0, 0, 0, 0])
	assert_eq(Modbus.serve(off, coils, _inputs()), off)
	assert_eq(coils[0], 0)


func test_fc15_writes_many_coils() -> void:
	var coils: PackedByteArray = Modbus.zeros(5)
	var bits: PackedByteArray = PackedByteArray([1, 1, 0, 0, 1])
	var reply: PackedByteArray = Modbus.serve(Modbus.write_coils_request(0, bits), coils, _inputs())
	assert_eq(reply, PackedByteArray([Modbus.FC_WRITE_MULTIPLE_COILS, 0, 0, 0, 5]))
	assert_eq(coils, bits)


func test_unknown_function_is_exception_1() -> void:
	var reply: PackedByteArray = Modbus.serve(Modbus.read_request(3, 0, 1), _coils(), _inputs())
	assert_eq(reply, PackedByteArray([0x83, Modbus.EX_ILLEGAL_FUNCTION]))


func test_out_of_range_address_is_exception_2() -> void:
	var read: PackedByteArray = Modbus.serve(
		Modbus.read_request(Modbus.FC_READ_COILS, 3, 5), _coils(), _inputs()
	)
	assert_eq(read, PackedByteArray([0x81, Modbus.EX_ILLEGAL_ADDRESS]))
	var write: PackedByteArray = Modbus.serve(
		PackedByteArray([Modbus.FC_WRITE_SINGLE_COIL, 0, 5, 0xFF, 0]), _coils(), _inputs()
	)
	assert_eq(write, PackedByteArray([0x85, Modbus.EX_ILLEGAL_ADDRESS]))


func test_bad_value_is_exception_3() -> void:
	var zero_count: PackedByteArray = Modbus.serve(
		Modbus.read_request(Modbus.FC_READ_COILS, 0, 0), _coils(), _inputs()
	)
	assert_eq(zero_count, PackedByteArray([0x81, Modbus.EX_ILLEGAL_VALUE]))
	var bad_coil: PackedByteArray = Modbus.serve(
		PackedByteArray([Modbus.FC_WRITE_SINGLE_COIL, 0, 0, 0x12, 0x34]), _coils(), _inputs()
	)
	assert_eq(bad_coil, PackedByteArray([0x85, Modbus.EX_ILLEGAL_VALUE]))
	var short: PackedByteArray = Modbus.serve(PackedByteArray([1, 0]), _coils(), _inputs())
	assert_eq(short, PackedByteArray([0x81, Modbus.EX_ILLEGAL_VALUE]))


func test_writes_never_touch_discrete_inputs() -> void:
	var inputs: PackedByteArray = _inputs()
	var all_on: PackedByteArray = PackedByteArray([1, 1, 1, 1, 1])
	var reply: PackedByteArray = Modbus.serve(
		Modbus.write_coils_request(0, all_on), Modbus.zeros(5), inputs
	)
	assert_eq(reply[0], Modbus.FC_WRITE_MULTIPLE_COILS)
	assert_eq(inputs, _inputs(), "discrete inputs are read-only")


func test_exception_reply_has_no_bits() -> void:
	var reply: PackedByteArray = Modbus.exception(Modbus.FC_READ_COILS, 2)
	assert_eq(Modbus.read_response_bits(reply, 5), PackedByteArray())
