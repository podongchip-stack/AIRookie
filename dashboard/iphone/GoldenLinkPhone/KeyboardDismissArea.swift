import SwiftUI
import UIKit

/// 입력창 터치는 그대로 두고, 그 밖을 누를 때만 키보드를 닫는다. 버튼 동작은 취소하지 않는다.
struct KeyboardDismissArea: UIViewRepresentable {
    func makeUIView(context: Context) -> DismissView { DismissView() }
    func updateUIView(_ uiView: DismissView, context: Context) {}
    static func dismantleUIView(_ uiView: DismissView, coordinator: ()) { uiView.detach() }

    final class DismissView: UIView, UIGestureRecognizerDelegate {
        private var tap: UITapGestureRecognizer?
        func detach() {
            if let tap { tap.view?.removeGestureRecognizer(tap) }
            tap = nil
        }
        override func didMoveToWindow() {
            super.didMoveToWindow()
            detach()
            guard let window else { return }
            let gesture = UITapGestureRecognizer(target: self, action: #selector(dismissKeyboard))
            gesture.cancelsTouchesInView = false
            gesture.delegate = self
            window.addGestureRecognizer(gesture)
            tap = gesture
        }
        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
            var view = touch.view
            while let current = view {
                if current is UITextField || current is UITextView { return false }
                view = current.superview
            }
            return true
        }
        @objc private func dismissKeyboard() { window?.endEditing(true) }
    }
}
