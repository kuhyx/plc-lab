extends GutTest
## Seeded boxes through the whole line: plant, server, TCP, mock PLC.
##
## The loop is Line._physics_process without the scene: dt = 1/60 and a PLC
## scan every MOCK_EVERY_TICKS, so a pass here is a pass in the window.

const PORT: int = 15020
const BOXES: int = 20
const MAX_TICKS: int = 60 * 300  # simulated time, not wall-clock


## A PLC that never queues a tall box, so it never diverts.
class NeverDiverts:
	extends ReferenceLogic

	func scan(di: PackedByteArray) -> PackedByteArray:
		fifo.clear()
		return super(di)


func _run(seed_value: int, logic: ReferenceLogic) -> PlantModel:
	var dt: float = 1.0 / 60.0
	var model: PlantModel = PlantModel.new(seed_value, BOXES)
	var server: ModbusServer = ModbusServer.new()
	assert_eq(server.listen(PORT), OK)
	var mock: MockPlc = MockPlc.new()
	mock.logic = logic
	assert_eq(mock.connect_to("127.0.0.1", PORT), OK)
	for tick: int in range(1, MAX_TICKS):
		model.start_pressed = tick < Line.AUTOSTART_TICKS
		server.poll(dt)
		if tick % Line.MOCK_EVERY_TICKS == 0:
			mock.cycle(server.poll)
		model.apply_coils(server.coils, server.is_online())
		model.step(dt)
		server.inputs = model.inputs()
		if model.spawned == BOXES and model.boxes.is_empty():
			break
	mock.client.close()
	server.stop()
	return model


func test_twenty_seeded_boxes_sort_cleanly() -> void:
	for seed_value: int in [1, 7, 42]:
		var model: PlantModel = _run(seed_value, ReferenceLogic.new())
		var label: String = "seed %d: %s" % [seed_value, model.exits]
		assert_eq(model.exited(), BOXES, label)
		assert_eq(model.missorted(), 0, label)
		assert_eq(model.jammed(), 0, label)
		assert_true(model.boxes.is_empty(), label)


func test_a_plc_that_never_diverts_missorts() -> void:
	var model: PlantModel = _run(7, NeverDiverts.new())
	assert_gt(model.missorted(), 0)
	assert_eq(model.exits["side_short"] + model.exits["side_tall"], 0)
