import Foundation
import Security

/// 동기화 키는 서버/구급차별 Keychain에 보관한다. 일반 설정·로그에는 기록하지 않는다.
enum RecordAccess {
    private static func query(_ apid: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "com.goldenlink.records",
         kSecAttrAccount as String: (Settings.httpBase?.absoluteString ?? "") + "|" + apid]
    }
    static func token(_ apid: String) -> String {
        var q = query(apid); q[kSecReturnData as String] = true; q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    @discardableResult
    static func save(_ token: String, apid: String) -> Bool {
        let q = query(apid)
        let data = Data(token.trimmingCharacters(in: .whitespacesAndNewlines).utf8)
        if data.isEmpty { let status = SecItemDelete(q as CFDictionary); return status == errSecSuccess || status == errSecItemNotFound }
        let attrs: [String: Any] = [kSecValueData as String: data, kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let status = SecItemUpdate(q as CFDictionary, attrs as CFDictionary)
        if status == errSecSuccess { return true }
        if status == errSecItemNotFound { return SecItemAdd(q.merging(attrs) { _, n in n } as CFDictionary, nil) == errSecSuccess }
        return false
    }
}
