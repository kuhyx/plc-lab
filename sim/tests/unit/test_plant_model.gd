extends GutTest
## The plant as pure state: belts, the diverter, sensors and the fail-safe.

const DT: float = 1.0 / 60.0


## A model whose spawner is spent, so only the boxes a test adds exist.
func _model_with(box_list: Array[PlantModel.Box]) -> PlantModel:
	var model: PlantModel = PlantModel.new(1, 1)
	model.spawned = 1
	model.boxes.append_array(box_list)
	return model


func _coils(main: int, side: int, diverter: int) -> PackedByteArray:
	return PackedByteArray([main, side, diverter, 0, 0])


func _run(model: PlantModel, seconds: float) -> void:
	for i: int in range(roundi(seconds / DT)):
		model.step(DT)


func test_short_box_runs_to_the_main_exit() -> void:
	var model: PlantModel = _model_with([PlantModel.Box.new(0, false, PlantModel.BELT_START)])
	model.apply_coils(_coils(1, 0, 0), true)
	_run(model, 10.0)
	assert_eq(model.exits["main_short"], 1)
	assert_eq(model.boxes.size(), 0)
	assert_eq(model.missorted(), 0)


func test_centred_tall_box_pushed_lands_on_side_belt() -> void:
	var model: PlantModel = _model_with([PlantModel.Box.new(0, true, PlantModel.DIVERTER_X)])
	model.apply_coils(_coils(0, 0, 1), true)
	_run(model, PlantModel.STROKE_TIME + 0.1)
	assert_true(model.boxes[0].on_side)
	model.apply_coils(_coils(0, 1, 0), true)
	_run(model, 5.0)
	assert_eq(model.exits["side_tall"], 1)
	assert_eq(model.jammed(), 0)


func test_clipped_box_jams() -> void:
	var off_centre: float = PlantModel.DIVERTER_X + PlantModel.PUSHER_HALF + 5.0
	var model: PlantModel = _model_with([PlantModel.Box.new(0, true, off_centre)])
	model.apply_coils(_coils(0, 0, 1), true)
	_run(model, PlantModel.STROKE_TIME)
	assert_eq(model.jammed(), 1)


func test_offline_turns_every_actuator_off() -> void:
	var model: PlantModel = PlantModel.new(1)
	var all_on: PackedByteArray = PackedByteArray([1, 1, 1, 1, 1])
	model.apply_coils(all_on, true)
	assert_eq(model.coils, all_on)
	model.apply_coils(all_on, false)
	assert_eq(model.coils, Modbus.zeros(IoMap.COIL_COUNT))


func test_photo_eyes_tell_heights_apart() -> void:
	var short: PlantModel = _model_with([PlantModel.Box.new(0, false, PlantModel.EYE_X)])
	assert_eq(short.inputs()[IoMap.DI_LOW_BEAM], 1)
	assert_eq(short.inputs()[IoMap.DI_HIGH_BEAM], 0)
	var tall: PlantModel = _model_with([PlantModel.Box.new(0, true, PlantModel.EYE_X)])
	assert_eq(tall.inputs()[IoMap.DI_LOW_BEAM], 1)
	assert_eq(tall.inputs()[IoMap.DI_HIGH_BEAM], 1)


func test_buttons_and_diverter_limits() -> void:
	var model: PlantModel = _model_with([])
	var idle: PackedByteArray = model.inputs()
	assert_eq(idle[IoMap.DI_STOP_OK], 1, "NC stop reads 1 when not pressed")
	assert_eq(idle[IoMap.DI_ESTOP_OK], 1)
	assert_eq(idle[IoMap.DI_DIVERTER_HOME], 1)
	assert_eq(idle[IoMap.DI_DIVERTER_OUT], 0)
	model.start_pressed = true
	model.stop_pressed = true
	model.estop_latched = true
	model.apply_coils(_coils(0, 0, 1), true)
	_run(model, PlantModel.STROKE_TIME + 0.1)
	var pressed: PackedByteArray = model.inputs()
	assert_eq(pressed[IoMap.DI_START], 1)
	assert_eq(pressed[IoMap.DI_STOP_OK], 0)
	assert_eq(pressed[IoMap.DI_ESTOP_OK], 0)
	assert_eq(pressed[IoMap.DI_DIVERTER_OUT], 1)
	assert_eq(pressed[IoMap.DI_DIVERTER_HOME], 0)


func test_exit_sensors_see_boxes_at_the_belt_ends() -> void:
	var at_main_end: float = PlantModel.BELT_END - PlantModel.SENSOR_INSET
	var model: PlantModel = _model_with([PlantModel.Box.new(0, false, at_main_end)])
	assert_eq(model.inputs()[IoMap.DI_MAIN_EXIT], 1)
	var side: PlantModel.Box = PlantModel.Box.new(1, true, PlantModel.DIVERTER_X)
	side.on_side = true
	side.side_pos = PlantModel.SIDE_LENGTH - PlantModel.SENSOR_INSET
	assert_eq(_model_with([side]).inputs()[IoMap.DI_SIDE_EXIT], 1)


func test_a_stopped_line_blocks_the_infeed() -> void:
	var model: PlantModel = PlantModel.new(1)
	_run(model, 10.0)
	assert_eq(model.spawned, 1, "the first box sits at the infeed")
	assert_eq(model.boxes.size(), 1)
