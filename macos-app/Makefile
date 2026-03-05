APP_NAME = Scouting Stats
BUNDLE_NAME = ScoutingTroopStats
SCHEME = $(BUNDLE_NAME)
BUILD_DIR = build
ARCHIVE_PATH = $(BUILD_DIR)/$(BUNDLE_NAME).xcarchive
EXPORT_PATH = $(BUILD_DIR)/export
APP_PATH = $(EXPORT_PATH)/$(APP_NAME).app
DMG_PATH = $(BUILD_DIR)/$(APP_NAME).dmg
DMG_VOLUME_NAME = $(APP_NAME)

.PHONY: all generate build archive dmg dmg-background clean

all: dmg

# Generate the Xcode project from project.yml (requires xcodegen)
generate:
	xcodegen generate

# Build the app in Release mode
build: generate
	xcodebuild -project $(BUNDLE_NAME).xcodeproj \
		-scheme $(SCHEME) \
		-configuration Release \
		-derivedDataPath $(BUILD_DIR)/DerivedData \
		build

# Create an archive for distribution
archive: generate
	xcodebuild -project $(BUNDLE_NAME).xcodeproj \
		-scheme $(SCHEME) \
		-configuration Release \
		-archivePath $(ARCHIVE_PATH) \
		archive

# Export the .app from the archive
export: archive
	@mkdir -p $(EXPORT_PATH)
	xcodebuild -exportArchive \
		-archivePath $(ARCHIVE_PATH) \
		-exportPath $(EXPORT_PATH) \
		-exportOptionsPlist ExportOptions.plist

# Build the app directly (no signing/archive — simplest path to a .app)
app: generate
	xcodebuild -project $(BUNDLE_NAME).xcodeproj \
		-scheme $(SCHEME) \
		-configuration Release \
		-derivedDataPath $(BUILD_DIR)/DerivedData \
		build
	@mkdir -p $(EXPORT_PATH)
	@cp -R "$$(find $(BUILD_DIR)/DerivedData -name '$(APP_NAME).app' -path '*/Release/*' | head -1)" "$(APP_PATH)"
	@echo "Built: $(APP_PATH)"

# Generate the DMG background image
dmg-background:
	@uv run --with Pillow scripts/generate-dmg-background.py

# Create a styled DMG with background, icon layout, and Applications shortcut
dmg: app dmg-background
	@rm -f "$(DMG_PATH)"
	APP_PATH="$(APP_PATH)" DMG_BACKGROUND="$(BUILD_DIR)/dmg-background.png" DMG_BACKGROUND_RETINA="$(BUILD_DIR)/dmg-background@2x.png" \
		uv run --with dmgbuild dmgbuild -s scripts/dmgbuild-settings.py "$(DMG_VOLUME_NAME)" "$(DMG_PATH)"
	@echo "DMG created: $(DMG_PATH)"

clean:
	rm -rf $(BUILD_DIR)
	rm -rf $(BUNDLE_NAME).xcodeproj
