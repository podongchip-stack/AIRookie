import SwiftUI

@main
struct GoldenLinkPhoneApp: App {
    @State private var model = PhoneModel()
    @State private var hospital = HospitalModel()

    var body: some Scene {
        WindowGroup {
            Group {
                if model.accessRequired {
                    AccessCodeEntry {
                        model.accessRequired = false
                    }
                } else if Settings.hospitalID != nil {
                    HospitalView(model: hospital) {
                        hospital.stop()
                        Settings.accessCode = ""
                        Settings.apid = ""
                        model.accessRequired = true
                    }
                } else {
                    ContentView().onAppear { model.start() }
                }
            }
            .environment(model)
        }
    }
}
