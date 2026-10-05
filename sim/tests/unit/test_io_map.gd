extends GutTest
## The address map: one name per address, addresses dense from 0.


func _dense(count: int) -> Array[int]:
	var out: Array[int] = []
	for i: int in range(count):
		out.append(i)
	return out


func test_every_input_has_one_name() -> void:
	assert_eq(IoMap.INPUT_NAMES.size(), IoMap.INPUT_COUNT)
	var addresses: Array[int] = [
		IoMap.DI_START,
		IoMap.DI_STOP_OK,
		IoMap.DI_ESTOP_OK,
		IoMap.DI_LOW_BEAM,
		IoMap.DI_HIGH_BEAM,
		IoMap.DI_AT_DIVERTER,
		IoMap.DI_DIVERTER_OUT,
		IoMap.DI_DIVERTER_HOME,
		IoMap.DI_MAIN_EXIT,
		IoMap.DI_SIDE_EXIT,
	]
	assert_eq(addresses, _dense(IoMap.INPUT_COUNT))


func test_every_coil_has_one_name() -> void:
	assert_eq(IoMap.COIL_NAMES.size(), IoMap.COIL_COUNT)
	var addresses: Array[int] = [
		IoMap.CO_MAIN_MOTOR,
		IoMap.CO_SIDE_MOTOR,
		IoMap.CO_DIVERTER,
		IoMap.CO_RUN_LAMP,
		IoMap.CO_FAULT_LAMP,
	]
	assert_eq(addresses, _dense(IoMap.COIL_COUNT))


func test_port_needs_no_root() -> void:
	assert_gt(IoMap.PORT, 1023)
