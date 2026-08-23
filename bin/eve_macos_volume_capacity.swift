import Foundation

let path = CommandLine.arguments.dropFirst().first ?? "/"
let url = URL(fileURLWithPath: path)
let keys: Set<URLResourceKey> = [
    .volumeAvailableCapacityKey,
    .volumeAvailableCapacityForImportantUsageKey,
    .volumeAvailableCapacityForOpportunisticUsageKey,
    .volumeNameKey,
    .volumeTotalCapacityKey
]

do {
    let values = try url.resourceValues(forKeys: keys)
    var payload: [String: Any] = [:]
    if let value = values.volumeName {
        payload["volume_name"] = value
    }
    if let value = values.volumeTotalCapacity {
        payload["total_bytes"] = value
    }
    if let value = values.volumeAvailableCapacity {
        payload["available_bytes"] = value
    }
    if let value = values.volumeAvailableCapacityForImportantUsage {
        payload["important_available_bytes"] = value
    }
    if let value = values.volumeAvailableCapacityForOpportunisticUsage {
        payload["opportunistic_available_bytes"] = value
    }
    let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
