/* Pure Node vm tests; no Application/ObjC or real UTM. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(__dirname + "/sw_i5_utm_result.js", "utf8"), context);
const plain = value => JSON.parse(JSON.stringify(value));
let count = 0;
function test(body) { body(); count += 1; }
function request(action, args) {
    return {schema_version: 1, scope: "i5-preparation-utm-rpc", uuid: context.TARGET_UUID,
        nonce: "a".repeat(32), manifest_sha256: "b".repeat(64), sequence: 0, action, args};
}
const calls = [];
const machine = {id: () => context.TARGET_UUID, status: () => "started",
    guestFiles: {byId: id => ({file: id})}, guestProcesses: {byId: id => ({process: id})}};
const app = {
    virtualMachines: {byId: id => { assert.equal(id, context.TARGET_UUID); return machine; }},
    openFile: (target, options, timeout) => { calls.push(["open", options, timeout]); return {id: () => 10}; },
    read: (target, options, timeout) => { calls.push(["read", target, options, timeout]); return Buffer.alloc(1024).toString("base64"); },
    write: (target, options, timeout) => calls.push(["write", target, options, timeout]),
    execute: (target, options, timeout) => { calls.push(["execute", options, timeout]); return {id: () => 777}; },
    getResult: (target, timeout) => { calls.push(["result", target, timeout]); return {exited: true, exitCode: 0,
        signalCode: 0, outputData: "eA==", errorData: ""}; },
    close: (target, timeout) => calls.push(["close", target, timeout])
};
const api = context.preparationNativeAPI(app);
test(() => {
    const response = context.preparationRPC(request("identify", {}), api);
    assert.deepEqual(plain(response.value), {uuid: context.TARGET_UUID, status: "started"});
});
test(() => {
    assert.equal(context.preparationRPC(request("open", {role: "lease"}), api).value, 10);
    assert.deepEqual(plain(calls.at(-1)), ["open", {at: "/run/radishlink-i5-preparation/" + "a".repeat(32) + "/control/lease.slot",
        for: "reading", updating: true}, {timeout: 2}]);
    context.preparationRPC(request("open", {role: "ack"}), api);
    assert.equal(calls.at(-1)[1].updating, false);
});
test(() => {
    context.preparationRPC(request("read", {handle: 10}), api);
    assert.deepEqual(plain(calls.at(-1)), ["read", {file: 10}, {atOffset: 0, from: "start position", forLength: 1024,
        base64Encoding: true, closing: false}, {timeout: 2}]);
});
test(() => {
    const data = Buffer.alloc(1024).toString("base64");
    assert.equal(context.preparationRPC(request("write", {handle: 10, data}), api).value, null);
    assert.deepEqual(plain(calls.at(-1)), ["write", {file: 10}, {withData: data, atOffset: 0, from: "start position",
        base64Encoding: true, closing: false}, {timeout: 2}]);
});
test(() => {
    context.preparationRPC(request("execute", {program_base64: "eA==", program_sha256: "c".repeat(64)}), api);
    const options = calls.at(-1)[1];
    assert.equal(options.at, "/usr/bin/python3");
    assert.equal(options.usingInput, "eA==");
    assert.equal(options.outputCapturing, true);
    assert.deepEqual(plain(options.withArguments), ["-I", "-B", "-", "--nonce", "a".repeat(32),
        "--preparation-apt", "--manifest-sha256", "b".repeat(64)]);
});
test(() => {
    const response = context.preparationRPC(request("result", {process: 777}), api);
    assert.deepEqual(plain(response.value), {exited: true, exit_code: 0, signal_code: 0, stdout_base64: "eA==", stderr_base64: ""});
    assert.deepEqual(plain(calls.at(-1)[1]), {process: 777});
});
test(() => {
    context.preparationRPC(request("close", {handle: 10}), api);
    assert.deepEqual(plain(calls.at(-1)), ["close", {file: 10}, {timeout: 2}]);
});
for (const change of [{uuid: "other"}, {nonce: "../escape"}, {schema_version: true}, {sequence: -1}, {extra: 1},
                      {action: "start"}, {args: {extra: 1}}]) {
    test(() => { const before = calls.length; assert.throws(() => context.preparationRPC({...request("identify", {}), ...change}, api));
        assert.equal(calls.length, before); });
}
for (const r of [request("open", {role: "../outside"}), request("read", {handle: true}),
                 request("write", {handle: 10, data: "eA=="}), request("write", {handle: 10, data: "x".repeat(1368)}),
                 request("execute", {program_base64: "eA==", program_sha256: "short"})]) {
    test(() => { const before = calls.length; assert.throws(() => context.preparationRPC(r, api)); assert.equal(calls.length, before); });
}
test(() => assert.throws(() => context.preparationRPC(request("result", {process: 777}),
    {result: () => ({exited: true, exitCode: 0, signalCode: 0, outputData: "A".repeat(2796205), errorData: ""})})));
test(() => assert.throws(() => context.run(["--preparation-rpc"])));
console.log("I5_UTM_RPC_SELF_TEST_PASS: " + count + " pure cases; no application calls");
