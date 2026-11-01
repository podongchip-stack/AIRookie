import SwiftUI

@main
struct GoldenLinkPhoneApp: App {
    @State private var model = PhoneModel()

    var body: some Scene {
        WindowGroup {
            Group {
                if model.accessRequired {
                    AccessCodeEntry {
                        model.accessRequired = false
                    }
                } else {
                    ContentView().onAppear { model.start() }
                }
            }
            .environment(model)
        }
    }
}
