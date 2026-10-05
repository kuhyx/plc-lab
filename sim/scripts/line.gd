class_name Line
extends Node2D
## The sorting line scene: the plant model, its Modbus server, and (with
## --mock) a built-in PLC. Run: godot --path sim -- [--mock] [--port=N]
## [--seed=N] [--boxes=N] [--autostart]. Keys: S start, X stop (both held),
## E e-stop toggle. --autostart holds start for the first AUTOSTART_TICKS.

const MOCK_EVERY_TICKS: int = 3  # ~50 ms scan at 60 physics ticks/s
const AUTOSTART_TICKS: int = 15

var model: PlantModel
var server: ModbusServer = ModbusServer.new()
var mock: MockPlc = null
var port: int = IoMap.PORT

var _tick: int = 0
var _listen_error: Error = OK
var _autostart: bool = false


func _ready() -> void:
	setup(OS.get_cmdline_user_args())


## Builds the plant, listens, and (with --mock) starts the mock PLC.
func setup(args: PackedStringArray) -> void:
	var options: Dictionary[String, String] = parse_args(args)
	port = _int_option(options, "port", IoMap.PORT)
	model = PlantModel.new(_int_option(options, "seed", 1), _int_option(options, "boxes", 0))
	_listen_error = server.listen(port)
	if _listen_error != OK:
		push_error("cannot listen on 127.0.0.1:%d (%s)" % [port, error_string(_listen_error)])
	_autostart = options.has("autostart")
	# Without our own server, the mock would reach whichever process owns the
	# port (e.g. a second instance driving the first one's plant).
	if options.has("mock") and _listen_error == OK:
		mock = MockPlc.new()
		var err: Error = mock.connect_to("127.0.0.1", port)
		if err != OK:
			push_error("mock PLC cannot connect: %s" % error_string(err))


func _exit_tree() -> void:
	server.stop()
	print(
		(
			"sorting line: spawned %d, exits %s, missorted %d, jammed %d, on belts %d, requests %d"
			% [
				model.spawned,
				model.exits,
				model.missorted(),
				model.jammed(),
				model.boxes.size(),
				server.requests
			]
		)
	)


func _physics_process(delta: float) -> void:
	_tick += 1
	if _autostart and _tick <= AUTOSTART_TICKS:
		model.start_pressed = _tick < AUTOSTART_TICKS
	server.poll(delta)
	if mock != null and _tick % MOCK_EVERY_TICKS == 0:
		mock.cycle(server.poll)
	model.apply_coils(server.coils, server.is_online())
	model.step(delta)
	server.inputs = model.inputs()
	queue_redraw()


func _draw() -> void:
	PlantPainter.draw(self, model, status_text())


func _unhandled_input(event: InputEvent) -> void:
	var key: InputEventKey = event as InputEventKey
	if key != null and not key.echo:
		match key.physical_keycode:
			KEY_S:
				model.start_pressed = key.pressed
			KEY_X:
				model.stop_pressed = key.pressed
			KEY_E:
				if key.pressed:
					model.estop_latched = not model.estop_latched
	var click: InputEventMouseButton = event as InputEventMouseButton
	if click != null and click.button_index == MOUSE_BUTTON_LEFT:
		_click(click.position, click.pressed)


func status_text() -> String:
	if _listen_error != OK:
		return (
			"cannot listen on 127.0.0.1:%d: %s; mock PLC not started"
			% [port, error_string(_listen_error)]
		)
	if server.is_online():
		return (
			"PLC online (%s) on 127.0.0.1:%d" % ["mock" if mock != null else "Modbus master", port]
		)
	return "PLC offline: every actuator off; waiting for a Modbus master on 127.0.0.1:%d" % port


## `--mock --port=1502` -> {"mock": "", "port": "1502"}.
static func parse_args(args: PackedStringArray) -> Dictionary[String, String]:
	var out: Dictionary[String, String] = {}
	for arg: String in args:
		if not arg.begins_with("--"):
			continue
		var parts: PackedStringArray = arg.substr(2).split("=", true, 1)
		out[parts[0]] = parts[1] if parts.size() > 1 else ""
	return out


static func _int_option(options: Dictionary[String, String], key: String, fallback: int) -> int:
	return options[key].to_int() if options.has(key) else fallback


func _click(at: Vector2, pressed: bool) -> void:
	if at.distance_to(PlantPainter.START_AT) <= PlantPainter.BUTTON_R:
		model.start_pressed = pressed
	elif at.distance_to(PlantPainter.STOP_AT) <= PlantPainter.BUTTON_R:
		model.stop_pressed = pressed
	elif pressed and at.distance_to(PlantPainter.ESTOP_AT) <= PlantPainter.BUTTON_R:
		model.estop_latched = not model.estop_latched
	else:
		model.start_pressed = false
		model.stop_pressed = false
