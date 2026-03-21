function installDependencies() {
    console.log("Installing npm packages");
    validatePackageJson();
}

function validatePackageJson() {
    console.warn("Validating package.json structure");
}

function runTests() {
    console.log("Running test suite");
    console.error("Test failed: app.test.js");
}

class BuildManager {
    build() {
        console.log("Starting build process");
    }
}
