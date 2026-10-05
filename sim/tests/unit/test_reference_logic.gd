extends GutTest
## The mock PLC's program: run latch, height FIFO and diverter sequence.


## Healthy inputs (stop and e-stop NC contacts closed) with `on` bits set.
func _di(on: Array[int]) -> PackedByteArray:
	var di: PackedByteArray = Modbus.zeros(IoMap.INPUT_COUNT)
	di[IoMap.DI_STOP_OK] = 1
	di[IoMap.DI_ESTOP_OK] = 1
	for index: int in on:
		di[index] = 1
	return di


## Scan each input image in turn; the coils from the last scan.
func _scan_all(logic: ReferenceLogic, images: Array[PackedByteArray]) -> PackedByteArray:
	var out: PackedByteArray = PackedByteArray()
	for di: PackedByteArray in images:
		out = logic.scan(di)
	return out


func _running_logic() -> ReferenceLogic:
	var logic: ReferenceLogic = ReferenceLogic.new()
	assert_eq(logic.scan(_di([IoMap.DI_START]))[IoMap.CO_RUN_LAMP], 1)
	return logic


func test_start_latches_the_run() -> void:
	var logic: ReferenceLogic = _running_logic()
	var out: PackedByteArray = logic.scan(_di([]))
	assert_true(logic.running)
	assert_eq(out[IoMap.CO_MAIN_MOTOR], 1)
	assert_eq(out[IoMap.CO_SIDE_MOTOR], 1)
	assert_eq(out[IoMap.CO_RUN_LAMP], 1)


func test_stop_wins_over_start() -> void:
	var logic: ReferenceLogic = _running_logic()
	var both: PackedByteArray = _di([IoMap.DI_START])
	both[IoMap.DI_STOP_OK] = 0
	var out: PackedByteArray = logic.scan(both)
	assert_false(logic.running)
	assert_eq(out, Modbus.zeros(IoMap.COIL_COUNT))


func test_estop_stops_and_lights_the_fault_lamp() -> void:
	var logic: ReferenceLogic = _running_logic()
	var latched: PackedByteArray = _di([IoMap.DI_START])
	latched[IoMap.DI_ESTOP_OK] = 0
	var out: PackedByteArray = logic.scan(latched)
	assert_false(logic.running)
	assert_eq(out[IoMap.CO_MAIN_MOTOR], 0)
	assert_eq(out[IoMap.CO_FAULT_LAMP], 1)


func test_fifo_queues_heights_in_order() -> void:
	var logic: ReferenceLogic = _running_logic()
	var images: Array[PackedByteArray] = [
		_di([IoMap.DI_LOW_BEAM]),
		_di([IoMap.DI_LOW_BEAM, IoMap.DI_HIGH_BEAM]),
		_di([IoMap.DI_LOW_BEAM]),
		_di([]),
		_di([IoMap.DI_LOW_BEAM]),
		_di([]),
	]
	assert_eq(_scan_all(logic, images)[IoMap.CO_MAIN_MOTOR], 1)
	var expected: Array[bool] = [true, false]
	assert_eq(logic.fifo, expected)


func test_tall_box_runs_the_diverter_sequence() -> void:
	var logic: ReferenceLogic = _running_logic()
	logic.fifo.append(true)
	var push: PackedByteArray = logic.scan(_di([IoMap.DI_AT_DIVERTER, IoMap.DI_DIVERTER_HOME]))
	assert_eq(logic.phase, ReferenceLogic.Phase.PUSHING)
	assert_eq(push[IoMap.CO_MAIN_MOTOR], 0, "the belt holds while pushing")
	assert_eq(push[IoMap.CO_DIVERTER], 1)
	var back: PackedByteArray = logic.scan(_di([IoMap.DI_DIVERTER_OUT]))
	assert_eq(logic.phase, ReferenceLogic.Phase.RETURNING)
	assert_eq(back[IoMap.CO_DIVERTER], 0)
	var home: PackedByteArray = logic.scan(_di([IoMap.DI_DIVERTER_HOME]))
	assert_eq(logic.phase, ReferenceLogic.Phase.IDLE)
	assert_eq(home[IoMap.CO_MAIN_MOTOR], 1)
	assert_true(logic.fifo.is_empty())


func test_short_box_passes_the_diverter() -> void:
	var logic: ReferenceLogic = _running_logic()
	logic.fifo.append(false)
	var out: PackedByteArray = logic.scan(_di([IoMap.DI_AT_DIVERTER]))
	assert_eq(logic.phase, ReferenceLogic.Phase.IDLE)
	assert_eq(out[IoMap.CO_DIVERTER], 0)
	assert_true(logic.fifo.is_empty(), "its height is consumed")
