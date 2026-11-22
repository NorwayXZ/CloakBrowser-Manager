// Native macOS AppKit compact icon tab bar for Playwright WebKit ("Playwright.app").
//
// Injected only into the UIProcess of headed WebKit iPhone launches via a local
// wrapper script (DYLD_INSERT_LIBRARIES is cleared immediately in the constructor
// so WebContent / Networking / GPU XPC subprocesses never load this library).
//
// Replaces the "Playwright: ..." window title in NSTitlebarView with:
//   [Profile Badge]  [Logo Tab 1] [Logo Tab 2] [Logo Tab 3] ...  [+]
// and stacks all BrowserWindowController windows into one synchronized single-window
// deck so links and new tabs stay inside one phone window.

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <stdlib.h>

@interface NSObject (PlaywrightMiniBrowser)
- (WKWebView *)webView;
@end

@class CloakTabDeck;
@class CloakTabBarView;

static NSString *gProfileName = @"iPhone";
static NSString *gStartURL = @"about:blank";
static NSMutableDictionary<NSString *, NSImage *> *gHostFavicons = nil;

static IMP gOrigMakeKeyAndOrderFront = NULL;
static IMP gOrigOrderWindow = NULL;
static IMP gOrigOrderOut = NULL;
static IMP gOrigPerformClose = NULL;
static IMP gOrigSendEvent = NULL;
static IMP gOrigSetTitle = NULL;

// Extract a meaningful brand initial from a URL host (e.g. demo.fingerprint.com -> "F").
static NSString *CloakBrandInitialForURL(NSURL *url) {
    NSString *host = [[url host] lowercaseString];
    if (!host || host.length == 0) return @"•";
    if ([host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"]) {
        return @"C";
    }
    NSArray<NSString *> *parts = [host componentsSeparatedByString:@"."];
    NSString *chosen = parts.firstObject;
    if (parts.count >= 3) {
        NSSet<NSString *> *generic = [NSSet setWithObjects:@"www", @"m", @"mobile", @"demo", @"app", @"my", @"auth", @"login", @"account", @"accounts", @"console", nil];
        if ([generic containsObject:chosen]) {
            chosen = parts[parts.count - 2];
        }
    } else if (parts.count == 2 && [chosen isEqualToString:@"www"]) {
        chosen = parts[1];
    }
    if (chosen.length == 0) return @"•";
    return [[chosen substringToIndex:1] uppercaseString];
}

static NSColor *CloakBrandColorForURL(NSURL *url) {
    NSString *host = [[url host] lowercaseString] ?: @"";
    if ([host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"]) {
        return [NSColor colorWithSRGBRed:0.06 green:0.73 blue:0.51 alpha:1.0]; // Cloak emerald
    }
    if (host.length == 0) {
        return [NSColor colorWithSRGBRed:0.39 green:0.45 blue:0.55 alpha:1.0];
    }
    NSUInteger hash = 2166136261u;
    for (NSUInteger i = 0; i < host.length; i++) {
        hash ^= [host characterAtIndex:i];
        hash *= 16777619u;
    }
    CGFloat hues[] = { 0.04, 0.08, 0.38, 0.48, 0.55, 0.60, 0.66, 0.75, 0.86, 0.94 };
    CGFloat hue = hues[hash % 10];
    return [NSColor colorWithHue:hue saturation:0.68 brightness:0.86 alpha:1.0];
}

// ── Per-Tab Model ────────────────────────────────────────────────────────────

@interface CloakTabItem : NSObject
@property (nonatomic, weak) NSWindow *window;
@property (nonatomic, weak) WKWebView *webView;
@property (nonatomic, strong) NSImage *favicon;
@property (nonatomic, copy) NSString *lastFaviconHost;
@property (nonatomic, assign) BOOL observing;
@property (nonatomic, assign) BOOL closingSingle;
- (NSString *)displayTitle;
- (NSURL *)currentURL;
- (void)stopObserving;
@end

@interface CloakTabDeck : NSObject
@property (nonatomic, strong) NSMutableArray<CloakTabItem *> *items;
@property (nonatomic, weak) CloakTabItem *activeItem;
@property (nonatomic, assign) NSRect sharedFrame;
@property (nonatomic, assign) BOOL hasSharedFrame;
@property (nonatomic, assign) BOOL switching;
@property (nonatomic, assign) BOOL closingAll;

+ (instancetype)shared;
- (BOOL)isManagedBrowserWindow:(NSWindow *)win;
- (CloakTabItem *)itemForWindow:(NSWindow *)win;
- (CloakTabItem *)registerWindowIfNeeded:(NSWindow *)win;
- (void)activateWindow:(NSWindow *)win;
- (void)selectTabAtIndex:(NSUInteger)idx;
- (void)closeTabAtIndex:(NSUInteger)idx;
- (void)closeOtherTabsExceptIndex:(NSUInteger)idx;
- (void)closeAllTabs;
- (void)openNewTab;
- (void)refreshAllBars;
- (void)scheduleFaviconFetchForItem:(CloakTabItem *)item;
@end

@implementation CloakTabItem

- (NSString *)displayTitle {
    NSString *t = self.webView.title;
    NSURL *u = self.webView.URL;
    NSString *host = u.host ?: @"";
    if ([host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"]) {
        return t.length > 0 ? t : @"起始页";
    }
    if (t.length > 0 && host.length > 0) {
        return [NSString stringWithFormat:@"%@ — %@", t, host];
    }
    if (t.length > 0) return t;
    if (u.absoluteString.length > 0) return u.absoluteString;
    return @"新标签页";
}

- (NSURL *)currentURL {
    return self.webView.URL;
}

- (void)observeValueForKeyPath:(NSString *)keyPath
                      ofObject:(id)object
                        change:(NSDictionary *)change
                       context:(void *)context {
    dispatch_async(dispatch_get_main_queue(), ^{
        if ([keyPath isEqualToString:@"URL"] || [keyPath isEqualToString:@"loading"]) {
            NSURL *u = self.webView.URL;
            NSString *host = [u.host lowercaseString];
            if (host.length > 0 && gHostFavicons[host]) {
                self.favicon = gHostFavicons[host];
                self.lastFaviconHost = host;
            } else if (!host || ![host isEqualToString:self.lastFaviconHost]) {
                self.favicon = nil;
                self.lastFaviconHost = host;
            }
            if (!self.webView.isLoading && host.length > 0 && !gHostFavicons[host]) {
                [[CloakTabDeck shared] scheduleFaviconFetchForItem:self];
            }
        }
        // Keep native window title text hidden whenever MiniBrowser updates window.title.
        if (self.window) {
            self.window.titleVisibility = NSWindowTitleHidden;
            self.window.representedURL = nil;
        }
        [[CloakTabDeck shared] refreshAllBars];
    });
}

- (void)stopObserving {
    if (!self.observing) return;
    self.observing = NO;
    WKWebView *wv = self.webView;
    if (wv) {
        @try { [wv removeObserver:self forKeyPath:@"title"]; } @catch (__unused id e) {}
        @try { [wv removeObserver:self forKeyPath:@"URL"]; } @catch (__unused id e) {}
        @try { [wv removeObserver:self forKeyPath:@"loading"]; } @catch (__unused id e) {}
    }
}

- (void)dealloc {
    [self stopObserving];
}

@end

// ── Native Titlebar Compact Logo Tab Strip View ──────────────────────────────

@interface CloakTabBarView : NSView <NSViewToolTipOwner>
@property (nonatomic, assign) NSInteger hoveredIndex;
@property (nonatomic, assign) BOOL hoveringClose;
@property (nonatomic, assign) BOOL hoveringPlus;
@property (nonatomic, assign) CGFloat scrollOffset;
@property (nonatomic, strong) NSTrackingArea *trackingArea;
@end

@implementation CloakTabBarView

- (instancetype)initWithFrame:(NSRect)frameRect {
    self = [super initWithFrame:frameRect];
    if (self) {
        _hoveredIndex = -1;
        self.wantsLayer = YES;
        self.layer.masksToBounds = NO;
    }
    return self;
}

- (BOOL)isFlipped {
    return YES;
}

- (BOOL)mouseDownCanMoveWindow {
    return NO;
}

- (BOOL)acceptsFirstMouse:(NSEvent *)event {
    return YES;
}

- (void)updateTrackingAreas {
    [super updateTrackingAreas];
    if (self.trackingArea) {
        [self removeTrackingArea:self.trackingArea];
    }
    NSTrackingAreaOptions opts = NSTrackingMouseMoved | NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect;
    self.trackingArea = [[NSTrackingArea alloc] initWithRect:self.bounds options:opts owner:self userInfo:nil];
    [self addTrackingArea:self.trackingArea];
}

// Compute horizontal metrics: [Badge] [Tab 0] [Tab 1] ... [+]
- (void)getBadgeRect:(NSRect *)outBadge
           stripRect:(NSRect *)outStrip
            plusRect:(NSRect *)outPlus
            tabWidth:(CGFloat *)outTabW
                 gap:(CGFloat *)outGap {
    CGFloat h = self.bounds.size.height;
    CGFloat w = self.bounds.size.width;

    NSDictionary *badgeAttrs = @{
        NSFontAttributeName: [NSFont systemFontOfSize:10.5 weight:NSFontWeightSemibold],
    };
    CGSize nameSize = [gProfileName sizeWithAttributes:badgeAttrs];
    CGFloat badgeW = MIN(48.0, MAX(22.0, ceil(nameSize.width) + 12.0));
    NSRect badge = NSMakeRect(0.0, floor((h - 20.0) * 0.5), badgeW, 20.0);

    CGFloat stripX = NSMaxX(badge) + 5.0;
    CGFloat maxStripW = MAX(24.0, w - 23.0 - 4.0 - stripX);

    NSUInteger count = MAX(1u, [CloakTabDeck shared].items.count);
    CGFloat gap = 3.0;
    CGFloat ideal = 28.0;
    CGFloat minW = 21.0;
    CGFloat fitW = floor((maxStripW - gap * (CGFloat)(count - 1)) / (CGFloat)count);
    CGFloat tabW = MIN(ideal, MAX(minW, fitW));

    CGFloat totalW = count * tabW + (count - 1) * gap;
    CGFloat stripW = MIN(maxStripW, totalW);
    NSRect strip = NSMakeRect(stripX, 0.0, stripW, h);
    NSRect plus = NSMakeRect(MIN(w - 22.0, NSMaxX(strip) + 4.0), floor((h - 20.0) * 0.5), 20.0, 20.0);

    if (self.scrollOffset > MAX(0.0, totalW - stripW)) {
        self.scrollOffset = MAX(0.0, totalW - stripW);
    }
    if (self.scrollOffset < 0.0) self.scrollOffset = 0.0;

    if (outBadge) *outBadge = badge;
    if (outStrip) *outStrip = strip;
    if (outPlus) *outPlus = plus;
    if (outTabW) *outTabW = tabW;
    if (outGap) *outGap = gap;
}

- (NSRect)rectForTabAtIndex:(NSUInteger)idx
                  stripRect:(NSRect)strip
                   tabWidth:(CGFloat)tabW
                        gap:(CGFloat)gap {
    CGFloat x = strip.origin.x + idx * (tabW + gap) - self.scrollOffset;
    CGFloat y = floor((self.bounds.size.height - 22.0) * 0.5);
    return NSMakeRect(x, y, tabW, 22.0);
}

- (NSRect)closeHitRectForTabRect:(NSRect)tabRect {
    return NSMakeRect(NSMaxX(tabRect) - 11.0, NSMinY(tabRect) - 1.0, 12.0, 12.0);
}

- (void)ensureActiveVisible {
    CloakTabDeck *deck = [CloakTabDeck shared];
    NSUInteger idx = [deck.items indexOfObjectIdenticalTo:deck.activeItem];
    if (idx == NSNotFound) return;
    NSRect strip; CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:NULL stripRect:&strip plusRect:NULL tabWidth:&tabW gap:&gap];
    CGFloat itemStart = idx * (tabW + gap);
    CGFloat itemEnd = itemStart + tabW;
    if (itemStart < self.scrollOffset) {
        self.scrollOffset = itemStart;
    } else if (itemEnd > self.scrollOffset + strip.size.width) {
        self.scrollOffset = itemEnd - strip.size.width;
    }
}

- (void)drawIconForItem:(CloakTabItem *)item inRect:(NSRect)iconRect {
    NSURL *url = [item currentURL];
    NSString *host = [[url host] lowercaseString] ?: @"";
    BOOL isStartPage = [host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"];

    if (!isStartPage && item.favicon) {
        [NSGraphicsContext saveGraphicsState];
        NSBezierPath *clip = [NSBezierPath bezierPathWithRoundedRect:iconRect xRadius:3.0 yRadius:3.0];
        [clip addClip];
        [NSGraphicsContext currentContext].imageInterpolation = NSImageInterpolationHigh;
        [item.favicon drawInRect:iconRect
                        fromRect:NSZeroRect
                       operation:NSCompositingOperationSourceOver
                        fraction:1.0
                  respectFlipped:YES
                           hints:nil];
        [NSGraphicsContext restoreGraphicsState];
    } else {
        NSColor *bg = CloakBrandColorForURL(url);
        NSBezierPath *box = [NSBezierPath bezierPathWithRoundedRect:iconRect xRadius:3.5 yRadius:3.5];
        [bg setFill];
        [box fill];

        NSString *letter = CloakBrandInitialForURL(url);
        NSDictionary *attrs = @{
            NSFontAttributeName: [NSFont systemFontOfSize:9.5 weight:NSFontWeightBold],
            NSForegroundColorAttributeName: [NSColor whiteColor],
        };
        CGSize sz = [letter sizeWithAttributes:attrs];
        NSPoint pt = NSMakePoint(
            NSMidX(iconRect) - sz.width * 0.5,
            NSMidY(iconRect) - sz.height * 0.5
        );
        [letter drawAtPoint:pt withAttributes:attrs];
    }

    if (item.webView.isLoading) {
        NSRect dot = NSMakeRect(NSMaxX(iconRect) - 4.0, NSMaxY(iconRect) - 4.0, 4.5, 4.5);
        NSBezierPath *dotPath = [NSBezierPath bezierPathWithOvalInRect:dot];
        [[NSColor colorWithSRGBRed:0.20 green:0.83 blue:0.60 alpha:1.0] setFill];
        [dotPath fill];
    }
}

- (void)drawRect:(NSRect)dirtyRect {
    [super drawRect:dirtyRect];

    CloakTabDeck *deck = [CloakTabDeck shared];
    NSArray<CloakTabItem *> *items = deck.items;
    BOOL isDark = YES;
    if (@available(macOS 10.14, *)) {
        NSAppearanceName best = [self.effectiveAppearance bestMatchFromAppearancesWithNames:@[NSAppearanceNameAqua, NSAppearanceNameDarkAqua]];
        isDark = [best isEqualToString:NSAppearanceNameDarkAqua];
    }

    NSRect badgeRect, stripRect, plusRect;
    CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:&badgeRect stripRect:&stripRect plusRect:&plusRect tabWidth:&tabW gap:&gap];

    // 1. Environment badge (e.g. "A")
    NSBezierPath *badgePath = [NSBezierPath bezierPathWithRoundedRect:badgeRect xRadius:5.0 yRadius:5.0];
    [(isDark ? [NSColor colorWithSRGBRed:0.06 green:0.73 blue:0.51 alpha:0.18]
             : [NSColor colorWithSRGBRed:0.05 green:0.60 blue:0.42 alpha:0.14]) setFill];
    [badgePath fill];
    [(isDark ? [NSColor colorWithSRGBRed:0.20 green:0.83 blue:0.60 alpha:0.42]
             : [NSColor colorWithSRGBRed:0.05 green:0.60 blue:0.42 alpha:0.38]) setStroke];
    badgePath.lineWidth = 1.0;
    [badgePath stroke];

    NSMutableParagraphStyle *truncStyle = [[NSMutableParagraphStyle alloc] init];
    truncStyle.lineBreakMode = NSLineBreakByTruncatingTail;
    truncStyle.alignment = NSTextAlignmentCenter;
    NSDictionary *badgeTextAttrs = @{
        NSFontAttributeName: [NSFont systemFontOfSize:10.5 weight:NSFontWeightSemibold],
        NSForegroundColorAttributeName: isDark
            ? [NSColor colorWithSRGBRed:0.43 green:0.91 blue:0.72 alpha:1.0]
            : [NSColor colorWithSRGBRed:0.04 green:0.47 blue:0.34 alpha:1.0],
        NSParagraphStyleAttributeName: truncStyle,
    };
    CGSize bTextSz = [gProfileName sizeWithAttributes:badgeTextAttrs];
    NSRect bTextRect = NSMakeRect(
        badgeRect.origin.x + 4.0,
        NSMidY(badgeRect) - bTextSz.height * 0.5,
        badgeRect.size.width - 8.0,
        bTextSz.height
    );
    [gProfileName drawInRect:bTextRect withAttributes:badgeTextAttrs];

    // 2. Compact Logo Tabs (clipped to stripRect)
    [NSGraphicsContext saveGraphicsState];
    [[NSBezierPath bezierPathWithRect:NSMakeRect(stripRect.origin.x - 1.0, 0.0, stripRect.size.width + 2.0, self.bounds.size.height)] addClip];

    for (NSUInteger i = 0; i < items.count; i++) {
        NSRect tabRect = [self rectForTabAtIndex:i stripRect:stripRect tabWidth:tabW gap:gap];
        if (NSMaxX(tabRect) < NSMinX(stripRect) || NSMinX(tabRect) > NSMaxX(stripRect)) {
            continue;
        }
        CloakTabItem *item = items[i];
        BOOL isActive = (item == deck.activeItem);
        BOOL isHover = ((NSInteger)i == self.hoveredIndex);

        NSBezierPath *pill = [NSBezierPath bezierPathWithRoundedRect:tabRect xRadius:6.0 yRadius:6.0];
        if (isActive) {
            [(isDark ? [NSColor colorWithWhite:1.0 alpha:0.17]
                     : [NSColor colorWithWhite:0.0 alpha:0.11]) setFill];
            [pill fill];
            [(isDark ? [NSColor colorWithWhite:1.0 alpha:0.26]
                     : [NSColor colorWithWhite:0.0 alpha:0.20]) setStroke];
            pill.lineWidth = 1.0;
            [pill stroke];
        } else if (isHover) {
            [(isDark ? [NSColor colorWithWhite:1.0 alpha:0.10]
                     : [NSColor colorWithWhite:0.0 alpha:0.07]) setFill];
            [pill fill];
        } else {
            [(isDark ? [NSColor colorWithWhite:1.0 alpha:0.04]
                     : [NSColor colorWithWhite:0.0 alpha:0.03]) setFill];
            [pill fill];
        }

        NSRect iconRect = NSMakeRect(
            floor(NSMidX(tabRect) - 7.5),
            floor(NSMidY(tabRect) - 7.5),
            15.0,
            15.0
        );
        [self drawIconForItem:item inRect:iconRect];

        // Active emerald underline indicator
        if (isActive) {
            CGFloat barW = MIN(14.0, tabW - 8.0);
            NSRect indRect = NSMakeRect(NSMidX(tabRect) - barW * 0.5, NSMaxY(tabRect) - 2.0, barW, 2.0);
            NSBezierPath *ind = [NSBezierPath bezierPathWithRoundedRect:indRect xRadius:1.0 yRadius:1.0];
            [[NSColor colorWithSRGBRed:0.20 green:0.83 blue:0.60 alpha:1.0] setFill];
            [ind fill];
        }

        // Hover close "×" micro-badge when multiple tabs are open
        if (isHover && items.count > 1) {
            NSRect closeHit = [self closeHitRectForTabRect:tabRect];
            NSRect closeDot = NSMakeRect(NSMaxX(tabRect) - 10.0, NSMinY(tabRect) + 1.0, 9.5, 9.5);
            NSBezierPath *cPath = [NSBezierPath bezierPathWithOvalInRect:closeDot];
            if (self.hoveringClose) {
                [[NSColor colorWithSRGBRed:0.94 green:0.27 blue:0.27 alpha:0.98] setFill];
            } else {
                [(isDark ? [NSColor colorWithSRGBRed:0.15 green:0.18 blue:0.22 alpha:0.94]
                         : [NSColor colorWithWhite:0.25 alpha:0.90]) setFill];
            }
            [cPath fill];

            NSBezierPath *xPath = [NSBezierPath bezierPath];
            CGFloat cx = NSMidX(closeDot), cy = NSMidY(closeDot), r = 2.1;
            [xPath moveToPoint:NSMakePoint(cx - r, cy - r)];
            [xPath lineToPoint:NSMakePoint(cx + r, cy + r)];
            [xPath moveToPoint:NSMakePoint(cx + r, cy - r)];
            [xPath lineToPoint:NSMakePoint(cx - r, cy + r)];
            xPath.lineWidth = 1.25;
            xPath.lineCapStyle = NSLineCapStyleRound;
            [[NSColor whiteColor] setStroke];
            [xPath stroke];
            (void)closeHit;
        }
    }
    [NSGraphicsContext restoreGraphicsState];

    // 3. "+" New Tab button
    NSBezierPath *plusPill = [NSBezierPath bezierPathWithRoundedRect:plusRect xRadius:5.0 yRadius:5.0];
    if (self.hoveringPlus) {
        [(isDark ? [NSColor colorWithWhite:1.0 alpha:0.13]
                 : [NSColor colorWithWhite:0.0 alpha:0.09]) setFill];
        [plusPill fill];
    }
    NSBezierPath *plusGlyph = [NSBezierPath bezierPath];
    CGFloat px = NSMidX(plusRect), py = NSMidY(plusRect), pr = 4.5;
    [plusGlyph moveToPoint:NSMakePoint(px - pr, py)];
    [plusGlyph lineToPoint:NSMakePoint(px + pr, py)];
    [plusGlyph moveToPoint:NSMakePoint(px, py - pr)];
    [plusGlyph lineToPoint:NSMakePoint(px, py + pr)];
    plusGlyph.lineWidth = 1.5;
    plusGlyph.lineCapStyle = NSLineCapStyleRound;
    [(isDark ? [NSColor colorWithWhite:0.88 alpha:(self.hoveringPlus ? 1.0 : 0.78)]
             : [NSColor colorWithWhite:0.20 alpha:(self.hoveringPlus ? 1.0 : 0.75)]) setStroke];
    [plusGlyph stroke];
}

- (void)updateHoverForPoint:(NSPoint)pt {
    NSRect badgeRect, stripRect, plusRect;
    CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:&badgeRect stripRect:&stripRect plusRect:&plusRect tabWidth:&tabW gap:&gap];

    NSInteger nextIdx = -1;
    BOOL nextClose = NO;
    BOOL nextPlus = NSPointInRect(pt, plusRect);

    NSArray<CloakTabItem *> *items = [CloakTabDeck shared].items;
    if (!nextPlus && NSPointInRect(pt, stripRect)) {
        for (NSUInteger i = 0; i < items.count; i++) {
            NSRect tr = [self rectForTabAtIndex:i stripRect:stripRect tabWidth:tabW gap:gap];
            if (NSPointInRect(pt, tr)) {
                nextIdx = (NSInteger)i;
                if (items.count > 1 && NSPointInRect(pt, [self closeHitRectForTabRect:tr])) {
                    nextClose = YES;
                }
                break;
            }
        }
    }

    NSString *tip = nil;
    if (nextPlus) {
        tip = @"新建标签页 (⌘T)";
    } else if (nextIdx >= 0 && (NSUInteger)nextIdx < items.count) {
        tip = [items[(NSUInteger)nextIdx] displayTitle];
    } else if (NSPointInRect(pt, badgeRect)) {
        tip = [NSString stringWithFormat:@"环境：%@（共 %lu 个标签页）", gProfileName, (unsigned long)items.count];
    }
    if ((tip ?: @"") != (self.toolTip ?: @"") && ![tip isEqualToString:self.toolTip]) {
        self.toolTip = tip;
    }

    if (nextIdx != self.hoveredIndex || nextClose != self.hoveringClose || nextPlus != self.hoveringPlus) {
        self.hoveredIndex = nextIdx;
        self.hoveringClose = nextClose;
        self.hoveringPlus = nextPlus;
        self.needsDisplay = YES;
    }
}

- (void)mouseMoved:(NSEvent *)event {
    [self updateHoverForPoint:[self convertPoint:event.locationInWindow fromView:nil]];
}

- (void)mouseExited:(NSEvent *)event {
    if (self.hoveredIndex != -1 || self.hoveringClose || self.hoveringPlus) {
        self.hoveredIndex = -1;
        self.hoveringClose = NO;
        self.hoveringPlus = NO;
        self.toolTip = nil;
        self.needsDisplay = YES;
    }
}

- (void)mouseDown:(NSEvent *)event {
    NSPoint pt = [self convertPoint:event.locationInWindow fromView:nil];
    NSRect badgeRect, stripRect, plusRect;
    CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:&badgeRect stripRect:&stripRect plusRect:&plusRect tabWidth:&tabW gap:&gap];

    if (NSPointInRect(pt, plusRect)) {
        [[CloakTabDeck shared] openNewTab];
        return;
    }

    NSArray<CloakTabItem *> *items = [CloakTabDeck shared].items;
    if (NSPointInRect(pt, stripRect)) {
        for (NSUInteger i = 0; i < items.count; i++) {
            NSRect tr = [self rectForTabAtIndex:i stripRect:stripRect tabWidth:tabW gap:gap];
            if (NSPointInRect(pt, tr)) {
                if (items.count > 1 && NSPointInRect(pt, [self closeHitRectForTabRect:tr])) {
                    [[CloakTabDeck shared] closeTabAtIndex:i];
                } else {
                    [[CloakTabDeck shared] selectTabAtIndex:i];
                }
                return;
            }
        }
    }

    // Clicking empty space or the profile badge drags the window naturally.
    [self.window performWindowDragWithEvent:event];
}

- (void)otherMouseDown:(NSEvent *)event {
    // Middle-click closes a tab when >1 tab is open.
    if (event.buttonNumber != 2) {
        [super otherMouseDown:event];
        return;
    }
    NSPoint pt = [self convertPoint:event.locationInWindow fromView:nil];
    NSRect stripRect; CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:NULL stripRect:&stripRect plusRect:NULL tabWidth:&tabW gap:&gap];
    NSArray<CloakTabItem *> *items = [CloakTabDeck shared].items;
    if (items.count > 1 && NSPointInRect(pt, stripRect)) {
        for (NSUInteger i = 0; i < items.count; i++) {
            if (NSPointInRect(pt, [self rectForTabAtIndex:i stripRect:stripRect tabWidth:tabW gap:gap])) {
                [[CloakTabDeck shared] closeTabAtIndex:i];
                return;
            }
        }
    }
}

- (void)scrollWheel:(NSEvent *)event {
    CGFloat delta = fabs(event.scrollingDeltaX) > fabs(event.scrollingDeltaY) ? -event.scrollingDeltaX : -event.scrollingDeltaY;
    if (fabs(delta) < 0.1) return;
    self.scrollOffset += delta;
    self.needsDisplay = YES;
}

- (NSMenu *)menuForEvent:(NSEvent *)event {
    NSPoint pt = [self convertPoint:event.locationInWindow fromView:nil];
    NSRect stripRect; CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:NULL stripRect:&stripRect plusRect:NULL tabWidth:&tabW gap:&gap];
    NSArray<CloakTabItem *> *items = [CloakTabDeck shared].items;
    if (!NSPointInRect(pt, stripRect)) return nil;

    NSInteger hit = -1;
    for (NSUInteger i = 0; i < items.count; i++) {
        if (NSPointInRect(pt, [self rectForTabAtIndex:i stripRect:stripRect tabWidth:tabW gap:gap])) {
            hit = (NSInteger)i;
            break;
        }
    }
    if (hit < 0) return nil;

    CloakTabItem *item = items[(NSUInteger)hit];
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Tab"];
    NSMenuItem *titleRow = [[NSMenuItem alloc] initWithTitle:[item displayTitle] action:nil keyEquivalent:@""];
    titleRow.enabled = NO;
    [menu addItem:titleRow];
    [menu addItem:[NSMenuItem separatorItem]];

    NSMenuItem *reloadItem = [[NSMenuItem alloc] initWithTitle:@"刷新此标签页" action:@selector(ctxReloadTab:) keyEquivalent:@""];
    reloadItem.target = self;
    reloadItem.tag = hit;
    [menu addItem:reloadItem];

    NSMenuItem *copyItem = [[NSMenuItem alloc] initWithTitle:@"复制网址" action:@selector(ctxCopyURL:) keyEquivalent:@""];
    copyItem.target = self;
    copyItem.tag = hit;
    [menu addItem:copyItem];

    if (items.count > 1) {
        [menu addItem:[NSMenuItem separatorItem]];
        NSMenuItem *closeItem = [[NSMenuItem alloc] initWithTitle:@"关闭此标签页" action:@selector(ctxCloseTab:) keyEquivalent:@""];
        closeItem.target = self;
        closeItem.tag = hit;
        [menu addItem:closeItem];

        NSMenuItem *closeOthers = [[NSMenuItem alloc] initWithTitle:@"关闭其他标签页" action:@selector(ctxCloseOtherTabs:) keyEquivalent:@""];
        closeOthers.target = self;
        closeOthers.tag = hit;
        [menu addItem:closeOthers];
    }
    return menu;
}

- (void)ctxReloadTab:(NSMenuItem *)sender {
    NSArray<CloakTabItem *> *items = [CloakTabDeck shared].items;
    if (sender.tag >= 0 && (NSUInteger)sender.tag < items.count) {
        [items[(NSUInteger)sender.tag].webView reload];
    }
}

- (void)ctxCopyURL:(NSMenuItem *)sender {
    NSArray<CloakTabItem *> *items = [CloakTabDeck shared].items;
    if (sender.tag >= 0 && (NSUInteger)sender.tag < items.count) {
        NSString *u = items[(NSUInteger)sender.tag].webView.URL.absoluteString;
        if (u.length > 0) {
            [[NSPasteboard generalPasteboard] clearContents];
            [[NSPasteboard generalPasteboard] setString:u forType:NSPasteboardTypeString];
        }
    }
}

- (void)ctxCloseTab:(NSMenuItem *)sender {
    if (sender.tag >= 0) [[CloakTabDeck shared] closeTabAtIndex:(NSUInteger)sender.tag];
}

- (void)ctxCloseOtherTabs:(NSMenuItem *)sender {
    if (sender.tag >= 0) [[CloakTabDeck shared] closeOtherTabsExceptIndex:(NSUInteger)sender.tag];
}

@end

// ── Single-Window Tab Deck Coordinator ───────────────────────────────────────

static const void *kTabBarAssocKey = &kTabBarAssocKey;

@implementation CloakTabDeck

+ (instancetype)shared {
    static CloakTabDeck *inst = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        inst = [[CloakTabDeck alloc] init];
    });
    return inst;
}

- (instancetype)init {
    self = [super init];
    if (self) {
        _items = [NSMutableArray array];
    }
    return self;
}

- (BOOL)isManagedBrowserWindow:(NSWindow *)win {
    if (!win) return NO;
    if (strcmp(class_getName([win class]), "CustomWindow") != 0) return NO;
    id wc = win.windowController;
    if (!wc || strcmp(class_getName([wc class]), "BrowserWindowController") != 0) return NO;
    return YES;
}

- (CloakTabItem *)itemForWindow:(NSWindow *)win {
    for (CloakTabItem *item in self.items) {
        if (item.window == win) return item;
    }
    return nil;
}

- (void)installTabBarOnWindow:(NSWindow *)win {
    win.animationBehavior = NSWindowAnimationBehaviorNone;
    win.titleVisibility = NSWindowTitleHidden;
    win.representedURL = nil;
    if (@available(macOS 10.12, *)) {
        win.tabbingMode = NSWindowTabbingModeDisallowed;
    }

    NSButton *zoomBtn = [win standardWindowButton:NSWindowZoomButton];
    NSView *tbView = zoomBtn.superview;
    if (!tbView) return;

    for (NSView *sub in tbView.subviews) {
        if ([sub isKindOfClass:[NSTextField class]]) {
            sub.hidden = YES;
            sub.alphaValue = 0.0;
        }
    }

    CloakTabBarView *existing = objc_getAssociatedObject(win, kTabBarAssocKey);
    CGFloat x = MAX(74.0, NSMaxX(zoomBtn.frame) + 6.0);
    CGFloat w = MAX(120.0, tbView.bounds.size.width - x - 6.0);
    CGFloat y = tbView.isFlipped ? 5.0 : MAX(37.0, round(NSMidY(zoomBtn.frame) - 14.5));
    NSRect barFrame = NSMakeRect(x, y, w, 28.0);

    if (!existing) {
        existing = [[CloakTabBarView alloc] initWithFrame:barFrame];
        existing.autoresizingMask = NSViewWidthSizable | (tbView.isFlipped ? NSViewMaxYMargin : NSViewMinYMargin);
        [tbView addSubview:existing positioned:NSWindowAbove relativeTo:nil];
        objc_setAssociatedObject(win, kTabBarAssocKey, existing, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    } else {
        existing.frame = barFrame;
        existing.needsDisplay = YES;
    }
}

- (CloakTabItem *)registerWindowIfNeeded:(NSWindow *)win {
    if (![self isManagedBrowserWindow:win]) return nil;
    CloakTabItem *existing = [self itemForWindow:win];
    if (existing) {
        [self installTabBarOnWindow:win];
        return existing;
    }

    CloakTabItem *item = [[CloakTabItem alloc] init];
    item.window = win;
    id wc = win.windowController;
    if ([wc respondsToSelector:@selector(webView)]) {
        WKWebView *wv = [wc webView];
        item.webView = wv;
        if (wv) {
            [wv addObserver:item forKeyPath:@"title" options:NSKeyValueObservingOptionNew context:NULL];
            [wv addObserver:item forKeyPath:@"URL" options:NSKeyValueObservingOptionNew context:NULL];
            [wv addObserver:item forKeyPath:@"loading" options:NSKeyValueObservingOptionNew context:NULL];
            item.observing = YES;
        }
    }

    [self.items addObject:item];
    [self installTabBarOnWindow:win];

    if (!self.hasSharedFrame) {
        self.sharedFrame = win.frame;
        self.hasSharedFrame = YES;
    } else {
        [win setFrame:self.sharedFrame display:NO];
    }

    NSNotificationCenter *nc = [NSNotificationCenter defaultCenter];
    [nc addObserver:self selector:@selector(onWindowMovedOrResized:) name:NSWindowDidMoveNotification object:win];
    [nc addObserver:self selector:@selector(onWindowMovedOrResized:) name:NSWindowDidResizeNotification object:win];
    [nc addObserver:self selector:@selector(onWindowWillClose:) name:NSWindowWillCloseNotification object:win];

    if (!self.activeItem) {
        self.activeItem = item;
    }
    [self refreshAllBars];
    return item;
}

- (void)activateWindow:(NSWindow *)win {
    CloakTabItem *item = [self registerWindowIfNeeded:win];
    if (!item) return;

    NSWindow *prevWin = self.activeItem.window;
    if (prevWin && prevWin != win) {
        self.sharedFrame = prevWin.frame;
        self.hasSharedFrame = YES;
    }

    self.switching = YES;
    [NSAnimationContext beginGrouping];
    [NSAnimationContext currentContext].duration = 0.0;
    if (self.hasSharedFrame) {
        [win setFrame:self.sharedFrame display:YES];
    }
    self.activeItem = item;
    [self installTabBarOnWindow:win];
    ((void (*)(id, SEL, id))gOrigMakeKeyAndOrderFront)(win, @selector(makeKeyAndOrderFront:), nil);
    if (prevWin && prevWin != win) {
        ((void (*)(id, SEL, id))gOrigOrderOut)(prevWin, @selector(orderOut:), nil);
    }
    [self refreshAllBars];
    CloakTabBarView *bar = objc_getAssociatedObject(win, kTabBarAssocKey);
    [bar ensureActiveVisible];
    bar.needsDisplay = YES;
    [NSAnimationContext endGrouping];
    self.switching = NO;
}

- (void)selectTabAtIndex:(NSUInteger)idx {
    if (idx >= self.items.count) return;
    CloakTabItem *target = self.items[idx];
    if (!target.window) return;
    if (target == self.activeItem) return;
    [self activateWindow:target.window];
}

- (void)closeTabAtIndex:(NSUInteger)idx {
    if (idx >= self.items.count) return;
    CloakTabItem *item = self.items[idx];
    NSWindow *win = item.window;
    item.closingSingle = YES;

    if (self.items.count > 1 && item == self.activeItem) {
        NSUInteger nextIdx = (idx + 1 < self.items.count) ? (idx + 1) : (idx - 1);
        [self selectTabAtIndex:nextIdx];
    }
    [item stopObserving];
    [self.items removeObjectIdenticalTo:item];
    [self refreshAllBars];
    if (win) {
        [win close];
    }
}

- (void)closeOtherTabsExceptIndex:(NSUInteger)idx {
    if (idx >= self.items.count) return;
    CloakTabItem *keep = self.items[idx];
    if (keep != self.activeItem && keep.window) {
        [self activateWindow:keep.window];
    }
    NSArray<CloakTabItem *> *snapshot = [self.items copy];
    for (CloakTabItem *item in snapshot) {
        if (item == keep) continue;
        item.closingSingle = YES;
        [item stopObserving];
        [self.items removeObjectIdenticalTo:item];
        [item.window close];
    }
    [self refreshAllBars];
}

- (void)closeAllTabs {
    if (self.closingAll) return;
    self.closingAll = YES;
    NSArray<CloakTabItem *> *snapshot = [self.items copy];
    [self.items removeAllObjects];
    for (CloakTabItem *item in snapshot) {
        [item stopObserving];
        [item.window close];
    }
}

- (void)openNewTab {
    WKWebView *wv = self.activeItem.webView;
    if (!wv) return;
    NSData *jsonData = [NSJSONSerialization dataWithJSONObject:@[gStartURL] options:0 error:nil];
    NSString *jsonArr = [[NSString alloc] initWithData:jsonData encoding:NSUTF8StringEncoding];
    NSString *js = [NSString stringWithFormat:@"void(window.open(%@[0], '_blank'))", jsonArr];
    [wv evaluateJavaScript:js completionHandler:nil];
}

- (void)refreshAllBars {
    for (CloakTabItem *item in self.items) {
        if (!item.window) continue;
        [self installTabBarOnWindow:item.window];
        CloakTabBarView *bar = objc_getAssociatedObject(item.window, kTabBarAssocKey);
        bar.needsDisplay = YES;
    }
}

- (void)onWindowMovedOrResized:(NSNotification *)note {
    if (self.switching) return;
    NSWindow *win = note.object;
    if (win == self.activeItem.window && win.isVisible) {
        self.sharedFrame = win.frame;
        self.hasSharedFrame = YES;
        [self installTabBarOnWindow:win];
    }
}

- (void)onWindowWillClose:(NSNotification *)note {
    NSWindow *win = note.object;
    [[NSNotificationCenter defaultCenter] removeObserver:self name:nil object:win];
    CloakTabItem *item = [self itemForWindow:win];
    if (!item) return;

    NSUInteger idx = [self.items indexOfObjectIdenticalTo:item];
    BOOL wasActive = (item == self.activeItem);
    [item stopObserving];
    [self.items removeObjectIdenticalTo:item];

    if (!self.closingAll && wasActive && self.items.count > 0) {
        NSUInteger nextIdx = (idx != NSNotFound && idx < self.items.count) ? idx : (self.items.count - 1);
        CloakTabItem *next = self.items[nextIdx];
        if (next.window) {
            [self activateWindow:next.window];
        }
    }
    [self refreshAllBars];
}

// Fetch favicon inside WKContentWorld.defaultClientWorld so:
// 1. Page scripts (CreepJS / Fingerprint.com) never see any JS execution or object.
// 2. Network fetch uses WKWebView's own proxied WKWebsiteDataStore (zero direct IP leak).
- (void)scheduleFaviconFetchForItem:(CloakTabItem *)item {
    if (!@available(macOS 11.0, *)) return;
    WKWebView *wv = item.webView;
    NSURL *pageURL = wv.URL;
    NSString *host = [pageURL.host lowercaseString];
    if (!wv || !host || host.length == 0) return;
    if ([host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"]) return;
    if (gHostFavicons[host]) {
        item.favicon = gHostFavicons[host];
        [self refreshAllBars];
        return;
    }

    static NSString *const kFaviconBody =
        @"try {\n"
         "  const links = [...document.querySelectorAll('link[rel*=\"icon\" i]')];\n"
         "  const candidates = links.map(l => l.href).filter(Boolean);\n"
         "  candidates.push(new URL('/favicon.ico', location.origin).href);\n"
         "  for (const href of candidates) {\n"
         "    try {\n"
         "      const ctrl = new AbortController();\n"
         "      const timer = setTimeout(() => ctrl.abort(), 3500);\n"
         "      const resp = await fetch(href, { signal: ctrl.signal, credentials: 'same-origin' });\n"
         "      clearTimeout(timer);\n"
         "      if (!resp.ok) continue;\n"
         "      const blob = await resp.blob();\n"
         "      if (!blob || blob.size === 0 || blob.size > 524288) continue;\n"
         "      const objUrl = URL.createObjectURL(blob);\n"
         "      try {\n"
         "        const img = new Image();\n"
         "        img.src = objUrl;\n"
         "        await img.decode();\n"
         "        const cv = document.createElement('canvas');\n"
         "        cv.width = 32; cv.height = 32;\n"
         "        const ctx = cv.getContext('2d');\n"
         "        ctx.drawImage(img, 0, 0, 32, 32);\n"
         "        return cv.toDataURL('image/png');\n"
         "      } finally { URL.revokeObjectURL(objUrl); }\n"
         "    } catch (_) {}\n"
         "  }\n"
         "  return null;\n"
         "} catch (_) { return null; }";

    __weak CloakTabItem *weakItem = item;
    [wv callAsyncJavaScript:kFaviconBody
                  arguments:@{}
                    inFrame:nil
             inContentWorld:[WKContentWorld defaultClientWorld]
          completionHandler:^(id result, NSError *error) {
        if (error || ![result isKindOfClass:[NSString class]]) return;
        NSString *dataURL = (NSString *)result;
        NSRange comma = [dataURL rangeOfString:@";base64,"];
        if (comma.location == NSNotFound) return;
        NSString *b64 = [dataURL substringFromIndex:NSMaxRange(comma)];
        NSData *raw = [[NSData alloc] initWithBase64EncodedString:b64 options:NSDataBase64DecodingIgnoreUnknownCharacters];
        if (!raw || raw.length == 0) return;
        NSImage *img = [[NSImage alloc] initWithData:raw];
        if (!img || img.size.width <= 0 || img.size.height <= 0) return;
        dispatch_async(dispatch_get_main_queue(), ^{
            gHostFavicons[host] = img;
            CloakTabItem *strongItem = weakItem;
            if (strongItem && [[strongItem.webView.URL.host lowercaseString] isEqualToString:host]) {
                strongItem.favicon = img;
            }
            [[CloakTabDeck shared] refreshAllBars];
        });
    }];
}

@end

// ── CustomWindow Method Swizzles ─────────────────────────────────────────────

static void Swizzled_makeKeyAndOrderFront(NSWindow *self, SEL _cmd, id sender) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if (!deck.switching && [deck isManagedBrowserWindow:self]) {
        [deck activateWindow:self];
        return;
    }
    ((void (*)(id, SEL, id))gOrigMakeKeyAndOrderFront)(self, _cmd, sender);
}

static void Swizzled_orderWindow(NSWindow *self, SEL _cmd, NSWindowOrderingMode place, NSInteger otherWin) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if (!deck.switching && place != NSWindowOut && [deck isManagedBrowserWindow:self]) {
        [deck activateWindow:self];
        return;
    }
    ((void (*)(id, SEL, NSWindowOrderingMode, NSInteger))gOrigOrderWindow)(self, _cmd, place, otherWin);
}

static void Swizzled_performClose(NSWindow *self, SEL _cmd, id sender) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if ([deck isManagedBrowserWindow:self]) {
        NSButton *redCloseBtn = [self standardWindowButton:NSWindowCloseButton];
        if (sender == redCloseBtn) {
            // Red traffic-light button closes the entire phone browser (all tabs).
            [deck closeAllTabs];
            return;
        }
        if (deck.items.count > 1) {
            // Cmd+W closes only the active tab when multiple tabs exist.
            NSUInteger idx = [deck.items indexOfObjectIdenticalTo:[deck itemForWindow:self]];
            if (idx != NSNotFound) {
                [deck closeTabAtIndex:idx];
                return;
            }
        }
    }
    ((void (*)(id, SEL, id))gOrigPerformClose)(self, _cmd, sender);
}

static void Swizzled_sendEvent(NSWindow *self, SEL _cmd, NSEvent *event) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if (event.type == NSEventTypeKeyDown && [deck isManagedBrowserWindow:self]) {
        NSEventModifierFlags mods = event.modifierFlags & NSEventModifierFlagDeviceIndependentFlagsMask;
        NSString *chars = [event.charactersIgnoringModifiers lowercaseString];
        if (mods == NSEventModifierFlagCommand) {
            if ([chars isEqualToString:@"t"]) {
                [deck openNewTab];
                return;
            }
            if ([chars isEqualToString:@"w"] && deck.items.count > 1) {
                NSUInteger idx = [deck.items indexOfObjectIdenticalTo:[deck itemForWindow:self]];
                if (idx != NSNotFound) {
                    [deck closeTabAtIndex:idx];
                    return;
                }
            }
            if (chars.length == 1) {
                unichar c = [chars characterAtIndex:0];
                if (c >= '1' && c <= '9') {
                    NSUInteger target = (c == '9') ? (deck.items.count > 0 ? deck.items.count - 1 : 0) : (NSUInteger)(c - '1');
                    if (target < deck.items.count) {
                        [deck selectTabAtIndex:target];
                        return;
                    }
                }
            }
        } else if ((mods & NSEventModifierFlagControl) && event.keyCode == 48 && deck.items.count > 1) {
            // Ctrl+Tab / Ctrl+Shift+Tab cycles tabs.
            NSUInteger cur = [deck.items indexOfObjectIdenticalTo:deck.activeItem];
            if (cur != NSNotFound) {
                BOOL rev = (mods & NSEventModifierFlagShift) != 0;
                NSUInteger next = rev ? ((cur + deck.items.count - 1) % deck.items.count) : ((cur + 1) % deck.items.count);
                [deck selectTabAtIndex:next];
                return;
            }
        }
    }
    ((void (*)(id, SEL, NSEvent *))gOrigSendEvent)(self, _cmd, event);
}

static void Swizzled_setTitle(NSWindow *self, SEL _cmd, NSString *title) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if ([deck isManagedBrowserWindow:self]) {
        self.titleVisibility = NSWindowTitleHidden;
        self.representedURL = nil;
        ((void (*)(id, SEL, NSString *))gOrigSetTitle)(self, _cmd, @"");
        [deck installTabBarOnWindow:self];
        return;
    }
    ((void (*)(id, SEL, NSString *))gOrigSetTitle)(self, _cmd, title);
}

static void InstallCloakWebKitTabs(void) {
    Class winCls = objc_getClass("CustomWindow");
    if (!winCls) return;

    Method mKey = class_getInstanceMethod(winCls, @selector(makeKeyAndOrderFront:));
    if (mKey) gOrigMakeKeyAndOrderFront = method_setImplementation(mKey, (IMP)Swizzled_makeKeyAndOrderFront);

    Method mOrder = class_getInstanceMethod(winCls, @selector(orderWindow:relativeTo:));
    if (mOrder) gOrigOrderWindow = method_setImplementation(mOrder, (IMP)Swizzled_orderWindow);

    Method mOut = class_getInstanceMethod(winCls, @selector(orderOut:));
    if (mOut) gOrigOrderOut = method_getImplementation(mOut);

    Method mClose = class_getInstanceMethod(winCls, @selector(performClose:));
    if (mClose) gOrigPerformClose = method_setImplementation(mClose, (IMP)Swizzled_performClose);

    Method mEvent = class_getInstanceMethod(winCls, @selector(sendEvent:));
    if (mEvent) gOrigSendEvent = method_setImplementation(mEvent, (IMP)Swizzled_sendEvent);

    Method mTitle = class_getInstanceMethod(winCls, @selector(setTitle:));
    if (mTitle) gOrigSetTitle = method_setImplementation(mTitle, (IMP)Swizzled_setTitle);
}

__attribute__((constructor))
static void CloakWebKitTabsEntry(void) {
    // Strip DYLD_INSERT_LIBRARIES immediately so WebContent / Networking / GPU XPC children never load us.
    unsetenv("DYLD_INSERT_LIBRARIES");

    @autoreleasepool {
        NSString *procName = [[NSProcessInfo processInfo] processName];
        if (![procName isEqualToString:@"Playwright"]) return;

        const char *envName = getenv("CLOAK_PROFILE_NAME");
        if (envName && envName[0]) {
            gProfileName = [NSString stringWithUTF8String:envName] ?: @"iPhone";
        }
        const char *envStart = getenv("CLOAK_START_URL");
        if (envStart && envStart[0]) {
            gStartURL = [NSString stringWithUTF8String:envStart] ?: @"about:blank";
        }
        gHostFavicons = [NSMutableDictionary dictionary];
        InstallCloakWebKitTabs();
    }
}
