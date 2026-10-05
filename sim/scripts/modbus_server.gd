class_name ModbusServer
extends RefCounted
## The plant's Modbus TCP server: OpenPLC (or the mock) connects as master.
##
## poll() is non-blocking: accept, read whatever arrived, answer every whole
## frame against `coils` and `inputs`. It also runs the fail-safe watchdog:
## with no request for WATCHDOG_S, is_online() turns false and the plant
## drops every actuator rather than keep the last command.

const WATCHDOG_S: float = 0.5

var coils: PackedByteArray = PackedByteArray()
var inputs: PackedByteArray = PackedByteArray()
var requests: int = 0

var _server: TCPServer = TCPServer.new()
var _peers: Array[StreamPeerTCP] = []
var _buffers: Array[PackedByteArray] = []
var _since_request: float = INF


func _init() -> void:
	coils = Modbus.zeros(IoMap.COIL_COUNT)
	inputs = Modbus.zeros(IoMap.INPUT_COUNT)


func listen(port: int, bind_address: String = "127.0.0.1") -> Error:
	return _server.listen(port, bind_address)


func stop() -> void:
	for peer: StreamPeerTCP in _peers:
		peer.disconnect_from_host()
	_peers.clear()
	_buffers.clear()
	_server.stop()


func is_online() -> bool:
	return _since_request < WATCHDOG_S


## Serve pending requests; `dt` advances the watchdog. `requests` counts them.
func poll(dt: float = 0.0) -> void:
	_since_request += dt
	while _server.is_connection_available():
		_peers.append(_server.take_connection())
		_buffers.append(PackedByteArray())
	var served: int = 0
	for i: int in range(_peers.size() - 1, -1, -1):
		served += _serve_peer(i)
	if served > 0:
		_since_request = 0.0
		requests += served


func _serve_peer(index: int) -> int:
	var peer: StreamPeerTCP = _peers[index]
	if peer.poll() != OK or peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		_peers.remove_at(index)
		_buffers.remove_at(index)
		return 0
	var available: int = peer.get_available_bytes()
	if available > 0:
		var got: Array = peer.get_partial_data(available)
		if got[0] == OK:
			var chunk: PackedByteArray = got[1]
			_buffers[index].append_array(chunk)
	var served: int = 0
	var size: int = Modbus.frame_size(_buffers[index])
	while size > 0:
		var request: PackedByteArray = _buffers[index].slice(0, size)
		_buffers[index] = _buffers[index].slice(size)
		var reply: PackedByteArray = Modbus.serve(Modbus.pdu_of(request), coils, inputs)
		var unit: int = request[6]
		var sent: Error = peer.put_data(Modbus.frame(Modbus.transaction_of(request), unit, reply))
		if sent == OK:
			served += 1
		size = Modbus.frame_size(_buffers[index])
	return served
