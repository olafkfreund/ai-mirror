# Build the ai-mirror-input virtual-device helper into the repo build tree.
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
WAYLAND_SCANNER ?= wayland-scanner
# The flake passes the store path; in `nix develop` it comes from the environment.
WLR_PROTO ?= $(error set WLR_PROTO to wlr-virtual-pointer-unstable-v1.xml)
BUILD ?= ../../build
BIN = $(BUILD)/ai-mirror-input

PKG_CFLAGS := $(shell pkg-config --cflags wayland-client xkbcommon)
PKG_LIBS := $(shell pkg-config --libs wayland-client xkbcommon)

GEN_H = $(BUILD)/virtual-keyboard-unstable-v1-client-protocol.h \
	$(BUILD)/wlr-virtual-pointer-unstable-v1-client-protocol.h
GEN_C = $(BUILD)/virtual-keyboard-unstable-v1-protocol.c \
	$(BUILD)/wlr-virtual-pointer-unstable-v1-protocol.c

all: $(BIN)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%-client-protocol.h: %.xml | $(BUILD)
	$(WAYLAND_SCANNER) client-header $< $@

$(BUILD)/%-protocol.c: %.xml | $(BUILD)
	$(WAYLAND_SCANNER) private-code $< $@

$(BUILD)/wlr-virtual-pointer-unstable-v1-client-protocol.h: $(WLR_PROTO) | $(BUILD)
	$(WAYLAND_SCANNER) client-header $< $@

$(BUILD)/wlr-virtual-pointer-unstable-v1-protocol.c: $(WLR_PROTO) | $(BUILD)
	$(WAYLAND_SCANNER) private-code $< $@

$(BIN): ai_mirror_input.c $(GEN_H) $(GEN_C)
	$(CC) $(CFLAGS) $(PKG_CFLAGS) -I$(BUILD) -o $@ ai_mirror_input.c $(GEN_C) $(PKG_LIBS)

clean:
	rm -rf $(BUILD)

.PHONY: all clean
