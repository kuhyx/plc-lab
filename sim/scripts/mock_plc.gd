class_name MockPlc
extends RefCounted
## A stand-in PLC: Modbus master + ReferenceLogic, scanned like OpenPLC.
##
## One cycle = read the discrete inputs (FC 2), scan, write the coils (FC 15),
## over real TCP, so the plant's server path is exercised end to end.

var logic: ReferenceLogic = ReferenceLogic.new()
var client: ModbusClient = ModbusClient.new()
var failures: int = 0
var last_ok: bool = false


func connect_to(host: String, port: int) -> Error:
	return client.connect_to(host, port)


## One scan; `last_ok` says whether both requests were answered. `pump`
## lets an in-process server answer while we wait.
func cycle(pump: Callable) -> void:
	var di: PackedByteArray = client.read_discrete_inputs(IoMap.INPUT_COUNT, pump)
	last_ok = di.size() == IoMap.INPUT_COUNT and client.write_coils(logic.scan(di), pump)
	if not last_ok:
		failures += 1
