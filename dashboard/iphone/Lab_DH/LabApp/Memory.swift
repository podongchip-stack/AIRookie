import Foundation
import os

/// 이 앱이 지금 쓰는 메모리(MB). 시스템이 앱을 끄는 기준(jetsam)에 쓰이는 phys_footprint.
func footprintMB() -> Double {
    var info = task_vm_info_data_t()
    var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
    let result = withUnsafeMutablePointer(to: &info) {
        $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
            task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
        }
    }
    return result == KERN_SUCCESS ? Double(info.phys_footprint) / 1_048_576 : 0
}

/// 앞으로 더 쓸 수 있는 메모리(MB). 0에 가까워지면 앱이 꺼진다.
func availableMB() -> Double { Double(os_proc_available_memory()) / 1_048_576 }
