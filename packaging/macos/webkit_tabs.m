// Native macOS AppKit compact icon tab bar, page zoom, and zero-leak monitor
// display scaling for Playwright WebKit ("Playwright.app").
//
// Injected only into the UIProcess of headed WebKit iPhone launches via a local
// wrapper script (DYLD_INSERT_LIBRARIES is cleared immediately in the constructor
// so WebContent / Networking / GPU XPC subprocesses never load this library).
//
// Replaces the "Playwright: ..." window title in NSTitlebarView with:
//   [Profile Badge]  [Logo Tab 1] [Logo Tab 2] ...  [+]   [125%]
// Stacks all BrowserWindowController windows into one synchronized single-window
// deck, supports Cmd + Scroll / Pinch / Cmd+/- page magnification, and scales
// the entire phone window on the Mac monitor via AppKit superview bounds scaling
// while keeping WKWebView's logical frame locked to exact iPhone dimensions
// (e.g. 393x852) so websites see zero viewport/screen discrepancy.

#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <math.h>
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
static NSString *gOriginFilePath = nil;
static NSString *gTabsFilePath = nil;
static CGFloat gBaseWidth = 393.0;
static CGFloat gBaseHeight = 852.0;
static CGFloat gInitialScaleEnv = 1.0;
static NSMutableDictionary<NSString *, NSImage *> *gHostFavicons = nil;

static BOOL CloakIsManagerStartPageURL(NSString *urlStr) {
    if (!urlStr || urlStr.length == 0) return NO;
    if (gStartURL.length > 0 && [urlStr isEqualToString:gStartURL]) return YES;
    NSURL *u = [NSURL URLWithString:urlStr];
    NSString *host = [[u host] lowercaseString] ?: @"";
    NSString *path = [u path] ?: @"";
    if (([host isEqualToString:@"127.0.0.1"] || [host isEqualToString:@"localhost"]) &&
        [path hasPrefix:@"/profile/"] && [path hasSuffix:@"/start"]) {
        return YES;
    }
    return NO;
}

static IMP gOrigMakeKeyAndOrderFront = NULL;
static IMP gOrigOrderWindow = NULL;
static IMP gOrigOrderOut = NULL;
static IMP gOrigPerformClose = NULL;
static IMP gOrigSendEvent = NULL;
static IMP gOrigSetTitle = NULL;
static IMP gOrigSetFrameDisplay = NULL;
static IMP gOrigSetFrameDisplayAnimate = NULL;
static IMP gOrigSetFrameOrigin = NULL;
static IMP gOrigSetFrameTopLeft = NULL;
static IMP gOrigCascadeTopLeft = NULL;
static BOOL gInProgrammaticFrameCall = NO;

static CGFloat CloakWindowChromeHeight(NSWindow *win) {
    if (win && win.contentView) {
        CGFloat diff = win.frame.size.height - win.contentView.frame.size.height;
        if (diff >= 28.0 && diff <= 140.0) {
            return diff;
        }
    }
    return 69.0;
}

static void CloakPersistGeometry(NSPoint pt, CGFloat scale) {
    if (!gOriginFilePath) return;
    NSString *s = [NSString stringWithFormat:@"%.1f,%.1f,%.3f\n", pt.x, pt.y, scale];
    [s writeToFile:gOriginFilePath atomically:YES encoding:NSUTF8StringEncoding error:nil];
}

static void CloakLoadSavedGeometry(NSPoint *outPt, BOOL *outHasOrigin, CGFloat *outScale) {
    if (outHasOrigin) *outHasOrigin = NO;
    if (outScale) *outScale = gInitialScaleEnv;
    if (!gOriginFilePath) return;

    NSString *s = [NSString stringWithContentsOfFile:gOriginFilePath encoding:NSUTF8StringEncoding error:nil];
    if (!s || s.length == 0) return;

    NSString *trimmed = [s stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    NSArray<NSString *> *parts = [trimmed componentsSeparatedByString:@","];
    if (parts.count >= 2) {
        NSString *p0 = [parts[0] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
        NSString *p1 = [parts[1] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
        if (p0.length > 0 && p1.length > 0) {
            CGFloat x = [p0 doubleValue];
            CGFloat y = [p1 doubleValue];
            if (isfinite(x) && isfinite(y)) {
                if (outPt) *outPt = NSMakePoint(x, y);
                if (outHasOrigin) *outHasOrigin = YES;
            }
        }
    }
    if (parts.count >= 3) {
        NSString *p2 = [parts[2] stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceCharacterSet]];
        if (p2.length > 0) {
            CGFloat sc = [p2 doubleValue];
            if (isfinite(sc) && sc >= 0.80 && sc <= 2.00) {
                if (outScale) *outScale = sc;
            }
        }
    }
}

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
@property (nonatomic, copy) NSString *knownURL;
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
@property (nonatomic, assign) BOOL hasSettledSize;
@property (nonatomic, assign) CGFloat displayScale;
@property (nonatomic, assign) BOOL enforcingViewBounds;
@property (nonatomic, assign) BOOL userDragging;
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
- (void)handleRedCloseButton:(id)sender;
- (void)persistSessionTabsAllowEmpty:(BOOL)allowEmpty;
- (void)openNewTab;
- (void)refreshAllBars;
- (void)scheduleFaviconFetchForItem:(CloakTabItem *)item;

- (CGFloat)clampDisplayScale:(CGFloat)scale forWindow:(NSWindow *)win;
- (NSSize)windowFrameSizeForScale:(CGFloat)scale window:(NSWindow *)win;
- (void)enforceWebViewLogicalBoundsForItem:(CloakTabItem *)item;
- (void)enforceWebViewLogicalBoundsForWindow:(NSWindow *)win;
- (void)setWindowDisplayScale:(CGFloat)scale;
- (CGFloat)activePageMagnification;
- (void)zoomActivePageByFactor:(CGFloat)factor centeredAtWindowPoint:(NSPoint)winPt useCenter:(BOOL)useCenter;
- (void)resetActivePageZoom;
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
            NSString *abs = u.absoluteString ?: @"";
            if ([abs hasPrefix:@"http://"] || [abs hasPrefix:@"https://"]) {
                self.knownURL = abs;
            }
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
            [[CloakTabDeck shared] persistSessionTabsAllowEmpty:NO];
        }
        // Keep native window title text hidden whenever MiniBrowser updates window.title.
        if (self.window) {
            self.window.titleVisibility = NSWindowTitleHidden;
            self.window.representedURL = nil;
        }
        [[CloakTabDeck shared] enforceWebViewLogicalBoundsForItem:self];
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

// ── Native Titlebar Compact Logo Tab Strip + Zoom Pill View ──────────────────

@interface CloakTabBarView : NSView <NSViewToolTipOwner>
@property (nonatomic, assign) NSInteger hoveredIndex;
@property (nonatomic, assign) BOOL hoveringClose;
@property (nonatomic, assign) BOOL hoveringPlus;
@property (nonatomic, assign) BOOL hoveringZoom;
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

// Compute horizontal metrics: [Badge] [Tab 0] [Tab 1] ... [+]   [125%]
- (void)getBadgeRect:(NSRect *)outBadge
           stripRect:(NSRect *)outStrip
            plusRect:(NSRect *)outPlus
            zoomRect:(NSRect *)outZoom
            tabWidth:(CGFloat *)outTabW
                 gap:(CGFloat *)outGap {
    CGFloat h = self.bounds.size.height;
    CGFloat w = self.bounds.size.width;
    CloakTabDeck *deck = [CloakTabDeck shared];

    NSDictionary *badgeAttrs = @{
        NSFontAttributeName: [NSFont systemFontOfSize:10.5 weight:NSFontWeightSemibold],
    };
    CGSize nameSize = [gProfileName sizeWithAttributes:badgeAttrs];
    CGFloat badgeW = MIN(46.0, MAX(22.0, ceil(nameSize.width) + 12.0));
    NSRect badge = NSMakeRect(0.0, floor((h - 20.0) * 0.5), badgeW, 20.0);

    CGFloat pageMag = [deck activePageMagnification];
    CGFloat zoomW = (pageMag > 1.02) ? 46.0 : 38.0;
    NSRect zoom = NSMakeRect(MAX(NSMaxX(badge) + 32.0, w - zoomW), floor((h - 20.0) * 0.5), zoomW, 20.0);

    CGFloat stripX = NSMaxX(badge) + 5.0;
    CGFloat rightLimit = NSMinX(zoom) - 4.0;
    CGFloat maxStripW = MAX(22.0, rightLimit - 21.0 - 3.0 - stripX);

    NSUInteger count = MAX(1u, deck.items.count);
    CGFloat gap = 3.0;
    CGFloat ideal = 28.0;
    CGFloat minW = 21.0;
    CGFloat fitW = floor((maxStripW - gap * (CGFloat)(count - 1)) / (CGFloat)count);
    CGFloat tabW = MIN(ideal, MAX(minW, fitW));

    CGFloat totalW = count * tabW + (count - 1) * gap;
    CGFloat stripW = MIN(maxStripW, totalW);
    NSRect strip = NSMakeRect(stripX, 0.0, stripW, h);
    NSRect plus = NSMakeRect(MIN(rightLimit - 20.0, NSMaxX(strip) + 3.0), floor((h - 20.0) * 0.5), 20.0, 20.0);

    if (self.scrollOffset > MAX(0.0, totalW - stripW)) {
        self.scrollOffset = MAX(0.0, totalW - stripW);
    }
    if (self.scrollOffset < 0.0) self.scrollOffset = 0.0;

    if (outBadge) *outBadge = badge;
    if (outStrip) *outStrip = strip;
    if (outPlus) *outPlus = plus;
    if (outZoom) *outZoom = zoom;
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
    [self getBadgeRect:NULL stripRect:&strip plusRect:NULL zoomRect:NULL tabWidth:&tabW gap:&gap];
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

    NSRect badgeRect, stripRect, plusRect, zoomRect;
    CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:&badgeRect stripRect:&stripRect plusRect:&plusRect zoomRect:&zoomRect tabWidth:&tabW gap:&gap];

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

        if (isActive) {
            CGFloat barW = MIN(14.0, tabW - 8.0);
            NSRect indRect = NSMakeRect(NSMidX(tabRect) - barW * 0.5, NSMaxY(tabRect) - 2.0, barW, 2.0);
            NSBezierPath *ind = [NSBezierPath bezierPathWithRoundedRect:indRect xRadius:1.0 yRadius:1.0];
            [[NSColor colorWithSRGBRed:0.20 green:0.83 blue:0.60 alpha:1.0] setFill];
            [ind fill];
        }

        if (isHover && items.count > 1) {
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

    // 4. Right-pinned Zoom / Window Scale Pill ([125%] or [🔍160%])
    CGFloat pageMag = [deck activePageMagnification];
    BOOL isPageZoomed = (pageMag > 1.02);
    NSBezierPath *zoomPill = [NSBezierPath bezierPathWithRoundedRect:zoomRect xRadius:5.0 yRadius:5.0];
    if (isPageZoomed) {
        [(isDark ? [NSColor colorWithSRGBRed:0.06 green:0.73 blue:0.51 alpha:(self.hoveringZoom ? 0.30 : 0.20)]
                 : [NSColor colorWithSRGBRed:0.05 green:0.60 blue:0.42 alpha:(self.hoveringZoom ? 0.22 : 0.14)]) setFill];
        [zoomPill fill];
        [(isDark ? [NSColor colorWithSRGBRed:0.20 green:0.83 blue:0.60 alpha:0.50]
                 : [NSColor colorWithSRGBRed:0.05 green:0.60 blue:0.42 alpha:0.42]) setStroke];
        zoomPill.lineWidth = 1.0;
        [zoomPill stroke];
    } else {
        [(isDark ? [NSColor colorWithWhite:1.0 alpha:(self.hoveringZoom ? 0.15 : 0.08)]
                 : [NSColor colorWithWhite:0.0 alpha:(self.hoveringZoom ? 0.11 : 0.06)]) setFill];
        [zoomPill fill];
        [(isDark ? [NSColor colorWithWhite:1.0 alpha:0.16]
                 : [NSColor colorWithWhite:0.0 alpha:0.14]) setStroke];
        zoomPill.lineWidth = 1.0;
        [zoomPill stroke];
    }

    long pct = lround((isPageZoomed ? pageMag : deck.displayScale) * 100.0);
    NSString *zoomLabel = [NSString stringWithFormat:@"%ld%%", pct];
    NSColor *zoomFg = isPageZoomed
        ? (isDark ? [NSColor colorWithSRGBRed:0.43 green:0.91 blue:0.72 alpha:1.0]
                  : [NSColor colorWithSRGBRed:0.04 green:0.47 blue:0.34 alpha:1.0])
        : (isDark ? [NSColor colorWithWhite:0.90 alpha:(self.hoveringZoom ? 1.0 : 0.85)]
                  : [NSColor colorWithWhite:0.18 alpha:(self.hoveringZoom ? 1.0 : 0.85)]);
    NSDictionary *zoomAttrs = @{
        NSFontAttributeName: [NSFont monospacedDigitSystemFontOfSize:9.5 weight:NSFontWeightSemibold],
        NSForegroundColorAttributeName: zoomFg,
    };
    CGSize zSz = [zoomLabel sizeWithAttributes:zoomAttrs];
    if (isPageZoomed) {
        // Tiny vector magnifier icon on the left of percentage
        CGFloat gx = zoomRect.origin.x + 5.0;
        CGFloat gy = NSMidY(zoomRect) - 4.0;
        NSBezierPath *lens = [NSBezierPath bezierPathWithOvalInRect:NSMakeRect(gx, gy, 6.0, 6.0)];
        lens.lineWidth = 1.2;
        [zoomFg setStroke];
        [lens stroke];
        NSBezierPath *handle = [NSBezierPath bezierPath];
        [handle moveToPoint:NSMakePoint(gx + 5.2, gy + 5.2)];
        [handle lineToPoint:NSMakePoint(gx + 7.6, gy + 7.6)];
        handle.lineWidth = 1.2;
        handle.lineCapStyle = NSLineCapStyleRound;
        [handle stroke];
        [zoomLabel drawAtPoint:NSMakePoint(gx + 9.5, NSMidY(zoomRect) - zSz.height * 0.5) withAttributes:zoomAttrs];
    } else {
        [zoomLabel drawAtPoint:NSMakePoint(NSMidX(zoomRect) - zSz.width * 0.5, NSMidY(zoomRect) - zSz.height * 0.5) withAttributes:zoomAttrs];
    }
}

- (void)updateHoverForPoint:(NSPoint)pt {
    NSRect badgeRect, stripRect, plusRect, zoomRect;
    CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:&badgeRect stripRect:&stripRect plusRect:&plusRect zoomRect:&zoomRect tabWidth:&tabW gap:&gap];

    NSInteger nextIdx = -1;
    BOOL nextClose = NO;
    BOOL nextPlus = NSPointInRect(pt, plusRect);
    BOOL nextZoom = !nextPlus && NSPointInRect(pt, zoomRect);

    CloakTabDeck *deck = [CloakTabDeck shared];
    NSArray<CloakTabItem *> *items = deck.items;
    if (!nextPlus && !nextZoom && NSPointInRect(pt, stripRect)) {
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
    if (nextZoom) {
        long winPct = lround(deck.displayScale * 100.0);
        long pagePct = lround([deck activePageMagnification] * 100.0);
        tip = [NSString stringWithFormat:@"窗口展示 %ld%% · 网页放大 %ld%%（点击调整窗口大小，按住 ⌘+滚轮放大网页）", winPct, pagePct];
    } else if (nextPlus) {
        tip = @"新建标签页 (⌘T)";
    } else if (nextIdx >= 0 && (NSUInteger)nextIdx < items.count) {
        tip = [items[(NSUInteger)nextIdx] displayTitle];
    } else if (NSPointInRect(pt, badgeRect)) {
        tip = [NSString stringWithFormat:@"环境：%@（共 %lu 个标签页）", gProfileName, (unsigned long)items.count];
    }
    if ((tip ?: @"") != (self.toolTip ?: @"") && ![tip isEqualToString:self.toolTip]) {
        self.toolTip = tip;
    }

    if (nextIdx != self.hoveredIndex || nextClose != self.hoveringClose || nextPlus != self.hoveringPlus || nextZoom != self.hoveringZoom) {
        self.hoveredIndex = nextIdx;
        self.hoveringClose = nextClose;
        self.hoveringPlus = nextPlus;
        self.hoveringZoom = nextZoom;
        self.needsDisplay = YES;
    }
}

- (void)mouseMoved:(NSEvent *)event {
    [self updateHoverForPoint:[self convertPoint:event.locationInWindow fromView:nil]];
}

- (void)mouseExited:(NSEvent *)event {
    if (self.hoveredIndex != -1 || self.hoveringClose || self.hoveringPlus || self.hoveringZoom) {
        self.hoveredIndex = -1;
        self.hoveringClose = NO;
        self.hoveringPlus = NO;
        self.hoveringZoom = NO;
        self.toolTip = nil;
        self.needsDisplay = YES;
    }
}

- (NSMenu *)buildZoomMenu {
    CloakTabDeck *deck = [CloakTabDeck shared];
    NSMenu *menu = [[NSMenu alloc] initWithTitle:@"Zoom"];

    NSMenuItem *hdr1 = [[NSMenuItem alloc] initWithTitle:@"窗口展示大小（不改手机指纹 393×852）" action:nil keyEquivalent:@""];
    hdr1.enabled = NO;
    [menu addItem:hdr1];

    struct { NSInteger pct; NSString *desc; } presets[] = {
        { 100, @"100%  原始大小" },
        { 115, @"115%  稍大" },
        { 125, @"125%  舒适推荐" },
        { 140, @"140%  大号清晰" },
        { 155, @"155%  超大尺寸" },
    };
    NSInteger curWinPct = lround(deck.displayScale * 100.0);
    for (size_t i = 0; i < sizeof(presets) / sizeof(presets[0]); i++) {
        NSMenuItem *mi = [[NSMenuItem alloc] initWithTitle:presets[i].desc action:@selector(ctxSetWindowScale:) keyEquivalent:@""];
        mi.target = self;
        mi.tag = presets[i].pct;
        if (labs(curWinPct - presets[i].pct) <= 3) {
            mi.state = NSControlStateValueOn;
        }
        [menu addItem:mi];
    }

    [menu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *hdr2 = [[NSMenuItem alloc] initWithTitle:@"当前网页放大镜（按住 ⌘ + 滚轮上推）" action:nil keyEquivalent:@""];
    hdr2.enabled = NO;
    [menu addItem:hdr2];

    NSMenuItem *zIn = [[NSMenuItem alloc] initWithTitle:@"放大网页内容 (⌘+)" action:@selector(ctxPageZoomIn:) keyEquivalent:@""];
    zIn.target = self;
    [menu addItem:zIn];

    NSMenuItem *zOut = [[NSMenuItem alloc] initWithTitle:@"缩小网页内容 (⌘-)" action:@selector(ctxPageZoomOut:) keyEquivalent:@""];
    zOut.target = self;
    [menu addItem:zOut];

    long pagePct = lround([deck activePageMagnification] * 100.0);
    NSString *resetTitle = (pagePct > 102)
        ? [NSString stringWithFormat:@"还原网页 100%%（当前 %ld%%，⌘0）", pagePct]
        : @"还原网页 100% (⌘0)";
    NSMenuItem *zReset = [[NSMenuItem alloc] initWithTitle:resetTitle action:@selector(ctxPageZoomReset:) keyEquivalent:@""];
    zReset.target = self;
    [menu addItem:zReset];

    return menu;
}

- (void)ctxSetWindowScale:(NSMenuItem *)sender {
    if (sender.tag >= 80 && sender.tag <= 200) {
        [[CloakTabDeck shared] setWindowDisplayScale:((CGFloat)sender.tag / 100.0)];
    }
}

- (void)ctxPageZoomIn:(__unused id)sender {
    [[CloakTabDeck shared] zoomActivePageByFactor:1.20 centeredAtWindowPoint:NSZeroPoint useCenter:YES];
}

- (void)ctxPageZoomOut:(__unused id)sender {
    [[CloakTabDeck shared] zoomActivePageByFactor:(1.0 / 1.20) centeredAtWindowPoint:NSZeroPoint useCenter:YES];
}

- (void)ctxPageZoomReset:(__unused id)sender {
    [[CloakTabDeck shared] resetActivePageZoom];
}

- (void)mouseDown:(NSEvent *)event {
    NSPoint pt = [self convertPoint:event.locationInWindow fromView:nil];
    NSRect badgeRect, stripRect, plusRect, zoomRect;
    CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:&badgeRect stripRect:&stripRect plusRect:&plusRect zoomRect:&zoomRect tabWidth:&tabW gap:&gap];

    if (NSPointInRect(pt, zoomRect)) {
        if ((event.modifierFlags & NSEventModifierFlagOption) != 0 && [[CloakTabDeck shared] activePageMagnification] > 1.02) {
            [[CloakTabDeck shared] resetActivePageZoom];
            return;
        }
        NSMenu *zoomMenu = [self buildZoomMenu];
        [zoomMenu popUpMenuPositioningItem:nil atLocation:NSMakePoint(zoomRect.origin.x, NSMaxY(zoomRect) + 3.0) inView:self];
        return;
    }

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
    CloakTabDeck *deck = [CloakTabDeck shared];
    deck.userDragging = YES;
    [self.window performWindowDragWithEvent:event];
    if (self.window) {
        deck.sharedFrame = self.window.frame;
        deck.hasSharedFrame = YES;
        deck.hasSettledSize = YES;
        CloakPersistGeometry(deck.sharedFrame.origin, deck.displayScale);
    }
    deck.userDragging = NO;
}

- (void)otherMouseDown:(NSEvent *)event {
    if (event.buttonNumber != 2) {
        [super otherMouseDown:event];
        return;
    }
    NSPoint pt = [self convertPoint:event.locationInWindow fromView:nil];
    NSRect stripRect, zoomRect; CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:NULL stripRect:&stripRect plusRect:NULL zoomRect:&zoomRect tabWidth:&tabW gap:&gap];
    if (NSPointInRect(pt, zoomRect)) {
        [[CloakTabDeck shared] resetActivePageZoom];
        return;
    }
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
    NSRect stripRect, zoomRect; CGFloat tabW = 28.0, gap = 3.0;
    [self getBadgeRect:NULL stripRect:&stripRect plusRect:NULL zoomRect:&zoomRect tabWidth:&tabW gap:&gap];
    if (NSPointInRect(pt, zoomRect)) {
        return [self buildZoomMenu];
    }
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

// ── Single-Window Tab Deck & Zero-Leak Scaling Coordinator ───────────────────

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
        NSPoint savedPt = NSZeroPoint;
        BOOL hasOrigin = NO;
        CGFloat savedScale = gInitialScaleEnv;
        CloakLoadSavedGeometry(&savedPt, &hasOrigin, &savedScale);
        _displayScale = savedScale;
        if (hasOrigin) {
            _sharedFrame = NSMakeRect(savedPt.x, savedPt.y, round(gBaseWidth * savedScale), round(gBaseHeight * savedScale) + 69.0);
            _hasSharedFrame = YES;
        }
        [[NSNotificationCenter defaultCenter] addObserver:self
                                                 selector:@selector(onAppWillTerminate:)
                                                     name:NSApplicationWillTerminateNotification
                                                   object:nil];
    }
    return self;
}

- (void)onAppWillTerminate:(__unused NSNotification *)note {
    [self persistSessionTabsAllowEmpty:NO];
    self.closingAll = YES;
}

- (void)persistSessionTabsAllowEmpty:(BOOL)allowEmpty {
    if (!gTabsFilePath || self.closingAll) return;

    // While initial restored tabs are still starting up with blank URLs, do not overwrite session_tabs.json.
    if (!allowEmpty) {
        for (CloakTabItem *it in self.items) {
            if (it.knownURL.length == 0 && it.webView.isLoading) {
                return;
            }
        }
    }

    NSMutableArray<NSString *> *urls = [NSMutableArray array];
    NSUInteger activeIdx = 0;
    BOOL hasExternalWebTab = NO;

    for (CloakTabItem *it in self.items) {
        NSString *u = it.webView.URL.absoluteString ?: @"";
        if (!([u hasPrefix:@"http://"] || [u hasPrefix:@"https://"])) {
            u = it.knownURL ?: @"";
        }
        if (!([u hasPrefix:@"http://"] || [u hasPrefix:@"https://"])) {
            continue;
        }
        if (it == self.activeItem) {
            activeIdx = urls.count;
        }
        if (CloakIsManagerStartPageURL(u)) {
            [urls addObject:@"__CLOAK_START_PAGE__"];
        } else {
            [urls addObject:u];
            hasExternalWebTab = YES;
        }
    }

    if (!hasExternalWebTab) {
        if (allowEmpty) {
            NSDictionary *emptyPayload = @{ @"urls": @[], @"active_index": @0 };
            NSData *data = [NSJSONSerialization dataWithJSONObject:emptyPayload options:0 error:nil];
            [data writeToFile:gTabsFilePath atomically:YES];
        }
        return;
    }

    if (activeIdx >= urls.count) activeIdx = 0;
    NSDictionary *payload = @{
        @"urls": urls,
        @"active_index": @(activeIdx),
    };
    NSData *data = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    if (data) {
        [data writeToFile:gTabsFilePath atomically:YES];
    }
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

- (CGFloat)clampDisplayScale:(CGFloat)scale forWindow:(NSWindow *)win {
    NSScreen *scr = win.screen ?: [NSScreen mainScreen];
    CGFloat chromeH = CloakWindowChromeHeight(win);
    CGFloat maxByScreen = 1.80;
    if (scr) {
        CGFloat availH = scr.visibleFrame.size.height - 8.0;
        if (availH > chromeH + 200.0) {
            maxByScreen = MIN(1.80, (availH - chromeH) / gBaseHeight);
        }
    }
    if (maxByScreen < 1.0) maxByScreen = 1.0;
    if (scale < 0.85) scale = 0.85;
    if (scale > maxByScreen) scale = maxByScreen;
    return scale;
}

- (NSSize)windowFrameSizeForScale:(CGFloat)scale window:(NSWindow *)win {
    CGFloat chromeH = CloakWindowChromeHeight(win);
    return NSMakeSize(round(gBaseWidth * scale), round(gBaseHeight * scale) + chromeH);
}

// Keep WKWebView's logical viewport locked to (gBaseWidth x gBaseHeight) while
// its superview stretches on the monitor, so AppKit scales on GPU with zero JS/DOM leak.
- (void)enforceWebViewLogicalBoundsForItem:(CloakTabItem *)item {
    if (!item || !item.webView || self.enforcingViewBounds) return;
    self.enforcingViewBounds = YES;
    WKWebView *wv = item.webView;
    wv.allowsMagnification = YES;
    wv.autoresizingMask = NSViewNotSizable;

    NSView *sup = wv.superview;
    NSSize baseSz = NSMakeSize(gBaseWidth, gBaseHeight);
    if (sup) {
        if (!NSEqualPoints(sup.bounds.origin, NSZeroPoint)) {
            [sup setBoundsOrigin:NSZeroPoint];
        }
        if (!NSEqualSizes(sup.bounds.size, baseSz)) {
            [sup setBoundsSize:baseSz];
        }
        sup.needsDisplay = YES;
    }
    NSRect baseRect = NSMakeRect(0.0, 0.0, gBaseWidth, gBaseHeight);
    if (!NSEqualRects(wv.frame, baseRect)) {
        wv.frame = baseRect;
    }
    self.enforcingViewBounds = NO;
}

- (void)enforceWebViewLogicalBoundsForWindow:(NSWindow *)win {
    CloakTabItem *item = [self itemForWindow:win];
    if (item) {
        [self enforceWebViewLogicalBoundsForItem:item];
    }
}

- (void)onWebViewGeometryChanged:(NSNotification *)note {
    if (self.enforcingViewBounds) return;
    NSView *v = note.object;
    if (![v isKindOfClass:[NSView class]] || !v.window) return;
    [self enforceWebViewLogicalBoundsForWindow:v.window];
}

- (void)setWindowDisplayScale:(CGFloat)scale {
    NSWindow *activeWin = self.activeItem.window;
    CGFloat clamped = [self clampDisplayScale:scale forWindow:activeWin];
    self.displayScale = clamped;
    NSSize newSize = [self windowFrameSizeForScale:clamped window:activeWin];

    if (self.hasSharedFrame) {
        CGFloat topY = NSMaxY(self.sharedFrame);
        CGFloat newX = self.sharedFrame.origin.x;
        CGFloat newY = topY - newSize.height;
        NSScreen *scr = activeWin.screen ?: [NSScreen mainScreen];
        if (scr) {
            NSRect vis = scr.visibleFrame;
            if (newY < NSMinY(vis)) newY = NSMinY(vis);
            if (newY + newSize.height > NSMaxY(vis)) newY = NSMaxY(vis) - newSize.height;
            if (newX + newSize.width > NSMaxX(vis)) newX = MAX(NSMinX(vis), NSMaxX(vis) - newSize.width);
        }
        self.sharedFrame = NSMakeRect(round(newX), round(newY), newSize.width, newSize.height);
    }
    self.hasSettledSize = YES;

    self.switching = YES;
    for (CloakTabItem *it in self.items) {
        if (!it.window) continue;
        BOOL isAct = (it == self.activeItem);
        if (self.hasSharedFrame) {
            if (gOrigSetFrameDisplay) {
                ((void (*)(id, SEL, NSRect, BOOL))gOrigSetFrameDisplay)(it.window, @selector(setFrame:display:), self.sharedFrame, isAct);
            } else {
                [it.window setFrame:self.sharedFrame display:isAct];
            }
        }
        [self enforceWebViewLogicalBoundsForItem:it];
    }
    self.switching = NO;

    if (self.hasSharedFrame) {
        CloakPersistGeometry(self.sharedFrame.origin, self.displayScale);
    }
    [self refreshAllBars];
}

- (CGFloat)activePageMagnification {
    WKWebView *wv = self.activeItem.webView;
    if (!wv) return 1.0;
    CGFloat m = wv.magnification;
    if (!isfinite(m) || m < 1.0) return 1.0;
    return m;
}

- (void)zoomActivePageByFactor:(CGFloat)factor centeredAtWindowPoint:(NSPoint)winPt useCenter:(BOOL)useCenter {
    WKWebView *wv = self.activeItem.webView;
    if (!wv) return;
    CGFloat cur = wv.magnification;
    if (!isfinite(cur) || cur < 1.0) cur = 1.0;
    CGFloat next = cur * factor;
    if (next < 1.02) next = 1.0;
    if (next > 4.0) next = 4.0;

    NSPoint ptInWv;
    if (useCenter) {
        ptInWv = NSMakePoint(gBaseWidth * 0.5, gBaseHeight * 0.5);
    } else {
        ptInWv = [wv convertPoint:winPt fromView:nil];
        if (ptInWv.x < 0.0) ptInWv.x = 0.0;
        if (ptInWv.x > gBaseWidth) ptInWv.x = gBaseWidth;
        if (ptInWv.y < 0.0) ptInWv.y = 0.0;
        if (ptInWv.y > gBaseHeight) ptInWv.y = gBaseHeight;
    }
    [wv setMagnification:next centeredAtPoint:ptInWv];
    [self refreshAllBars];
}

- (void)resetActivePageZoom {
    WKWebView *wv = self.activeItem.webView;
    if (!wv) return;
    [wv setMagnification:1.0 centeredAtPoint:NSMakePoint(gBaseWidth * 0.5, gBaseHeight * 0.5)];
    [self refreshAllBars];
}

- (void)installTabBarOnWindow:(NSWindow *)win {
    win.animationBehavior = NSWindowAnimationBehaviorNone;
    [win setFrameAutosaveName:@""];
    win.titleVisibility = NSWindowTitleHidden;
    win.representedURL = nil;
    if (@available(macOS 10.12, *)) {
        win.tabbingMode = NSWindowTabbingModeDisallowed;
    }

    // Wire the red traffic-light close button so clicking 🔴 closes the entire phone browser
    // in ONE click (while keeping all open tabs saved for the next launch!).
    NSButton *redCloseBtn = [win standardWindowButton:NSWindowCloseButton];
    if (redCloseBtn) {
        redCloseBtn.target = self;
        redCloseBtn.action = @selector(handleRedCloseButton:);
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
        [self enforceWebViewLogicalBoundsForItem:existing];
        [self installTabBarOnWindow:win];
        return existing;
    }

    CloakTabItem *item = [[CloakTabItem alloc] init];
    item.window = win;
    id wc = win.windowController;
    if ([wc isKindOfClass:[NSWindowController class]]) {
        [(NSWindowController *)wc setShouldCascadeWindows:NO];
    }

    NSNotificationCenter *nc = [NSNotificationCenter defaultCenter];
    if ([wc respondsToSelector:@selector(webView)]) {
        WKWebView *wv = [wc webView];
        item.webView = wv;
        if (wv) {
            [wv addObserver:item forKeyPath:@"title" options:NSKeyValueObservingOptionNew context:NULL];
            [wv addObserver:item forKeyPath:@"URL" options:NSKeyValueObservingOptionNew context:NULL];
            [wv addObserver:item forKeyPath:@"loading" options:NSKeyValueObservingOptionNew context:NULL];
            item.observing = YES;

            wv.postsFrameChangedNotifications = YES;
            [nc addObserver:self selector:@selector(onWebViewGeometryChanged:) name:NSViewFrameDidChangeNotification object:wv];
            if (wv.superview) {
                wv.superview.postsFrameChangedNotifications = YES;
                [nc addObserver:self selector:@selector(onWebViewGeometryChanged:) name:NSViewFrameDidChangeNotification object:wv.superview];
            }
        }
    }

    [self.items addObject:item];
    [self enforceWebViewLogicalBoundsForItem:item];

    CGFloat clampedScale = [self clampDisplayScale:self.displayScale forWindow:win];
    self.displayScale = clampedScale;
    NSSize targetSize = [self windowFrameSizeForScale:clampedScale window:win];

    if (self.items.count == 1) {
        NSScreen *scr = win.screen ?: [NSScreen mainScreen];
        CGFloat x = self.hasSharedFrame ? self.sharedFrame.origin.x : win.frame.origin.x;
        CGFloat y = self.hasSharedFrame ? self.sharedFrame.origin.y : (NSMaxY(win.frame) - targetSize.height);
        if (scr) {
            NSRect vis = scr.visibleFrame;
            if (y < NSMinY(vis)) y = NSMinY(vis);
            if (y + targetSize.height > NSMaxY(vis)) y = NSMaxY(vis) - targetSize.height;
            if (x + targetSize.width > NSMaxX(vis)) x = MAX(NSMinX(vis), NSMaxX(vis) - targetSize.width);
            if (x < NSMinX(vis)) x = NSMinX(vis);
        }
        self.sharedFrame = NSMakeRect(round(x), round(y), targetSize.width, targetSize.height);
        self.hasSharedFrame = YES;
        self.hasSettledSize = YES;
    } else {
        self.sharedFrame = NSMakeRect(self.sharedFrame.origin.x, self.sharedFrame.origin.y, targetSize.width, targetSize.height);
        self.hasSettledSize = YES;
    }

    self.switching = YES;
    if (gOrigSetFrameDisplay) {
        ((void (*)(id, SEL, NSRect, BOOL))gOrigSetFrameDisplay)(win, @selector(setFrame:display:), self.sharedFrame, NO);
    } else {
        [win setFrame:self.sharedFrame display:NO];
    }
    [self enforceWebViewLogicalBoundsForItem:item];
    self.switching = NO;

    [self installTabBarOnWindow:win];

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

    self.switching = YES;
    [NSAnimationContext beginGrouping];
    [NSAnimationContext currentContext].duration = 0.0;
    if (self.hasSharedFrame) {
        if (gOrigSetFrameDisplay) {
            ((void (*)(id, SEL, NSRect, BOOL))gOrigSetFrameDisplay)(win, @selector(setFrame:display:), self.sharedFrame, YES);
        } else {
            [win setFrame:self.sharedFrame display:YES];
        }
    }
    [self enforceWebViewLogicalBoundsForItem:item];
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
    [self persistSessionTabsAllowEmpty:NO];
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
    [self persistSessionTabsAllowEmpty:YES];
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
    [self persistSessionTabsAllowEmpty:YES];
    [self refreshAllBars];
}

- (void)handleRedCloseButton:(__unused id)sender {
    [self closeAllTabs];
}

- (void)closeAllTabs {
    if (self.closingAll) return;
    [self persistSessionTabsAllowEmpty:NO];
    self.closingAll = YES;
    NSArray<CloakTabItem *> *snapshot = [self.items copy];
    [self.items removeAllObjects];
    for (CloakTabItem *item in snapshot) {
        [item stopObserving];
        if (item.window && gOrigOrderOut) {
            ((void (*)(id, SEL, id))gOrigOrderOut)(item.window, @selector(orderOut:), nil);
        }
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
    if (self.switching || gInProgrammaticFrameCall) return;
    NSWindow *win = note.object;
    if (win != self.activeItem.window || !win.isVisible) return;

    NSRect cur = win.frame;
    if (win.inLiveResize) {
        self.sharedFrame = cur;
    } else if (self.hasSettledSize) {
        self.sharedFrame = NSMakeRect(cur.origin.x, cur.origin.y, self.sharedFrame.size.width, self.sharedFrame.size.height);
    } else {
        self.sharedFrame = cur;
    }
    self.hasSharedFrame = YES;
    [self enforceWebViewLogicalBoundsForWindow:win];
    CloakPersistGeometry(self.sharedFrame.origin, self.displayScale);
    [self refreshAllBars];
}

- (void)onWindowWillClose:(NSNotification *)note {
    NSWindow *win = note.object;
    NSNotificationCenter *nc = [NSNotificationCenter defaultCenter];
    [nc removeObserver:self name:nil object:win];
    CloakTabItem *item = [self itemForWindow:win];
    if (!item) return;

    if (item.webView) {
        [nc removeObserver:self name:nil object:item.webView];
        if (item.webView.superview) {
            [nc removeObserver:self name:nil object:item.webView.superview];
        }
    }

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
         "      const rawBlob = await resp.blob();\n"
         "      if (!rawBlob || rawBlob.size === 0 || rawBlob.size > 524288) continue;\n"
         "      const objUrl = URL.createObjectURL(rawBlob);\n"
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
        if (sender == redCloseBtn || deck.items.count <= 1) {
            [deck closeAllTabs];
            return;
        }
        NSUInteger idx = [deck.items indexOfObjectIdenticalTo:[deck itemForWindow:self]];
        if (idx != NSNotFound) {
            [deck closeTabAtIndex:idx];
            return;
        }
    }
    ((void (*)(id, SEL, id))gOrigPerformClose)(self, _cmd, sender);
}

static void Swizzled_sendEvent(NSWindow *self, SEL _cmd, NSEvent *event) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if ([deck isManagedBrowserWindow:self]) {
        NSEventType type = event.type;
        NSEventModifierFlags mods = event.modifierFlags & NSEventModifierFlagDeviceIndependentFlagsMask;

        // 1. Command + Scroll Wheel -> Smooth Page Content Zoom centered at cursor!
        if (type == NSEventTypeScrollWheel && (mods & NSEventModifierFlagCommand) != 0) {
            // Ignore post-flick trackpad momentum so pressing Cmd+C/Cmd+T right after scrolling never zooms accidentally.
            if (event.momentumPhase == NSEventPhaseNone) {
                CGFloat upDelta = event.isDirectionInvertedFromDevice ? -event.scrollingDeltaY : event.scrollingDeltaY;
                if (fabs(upDelta) > 0.005) {
                    CGFloat factor = 1.0;
                    if (event.hasPreciseScrollingDeltas) {
                        CGFloat clamped = MAX(-40.0, MIN(40.0, upDelta));
                        factor = exp(clamped * 0.0085);
                    } else {
                        CGFloat step = upDelta;
                        if (fabs(step) < 0.65) step = copysign(0.65, step);
                        step = MAX(-2.5, MIN(2.5, step));
                        factor = pow(1.15, step);
                    }
                    [deck zoomActivePageByFactor:factor centeredAtWindowPoint:event.locationInWindow useCenter:NO];
                }
            }
            return;
        }

        // 2. Trackpad Two-Finger Pinch Magnification -> clamp >= 1.0 and update pill!
        if (type == NSEventTypeMagnify) {
            ((void (*)(id, SEL, NSEvent *))gOrigSendEvent)(self, _cmd, event);
            WKWebView *wv = deck.activeItem.webView;
            if (wv && wv.magnification < 1.0) {
                [wv setMagnification:1.0 centeredAtPoint:NSMakePoint(gBaseWidth * 0.5, gBaseHeight * 0.5)];
            }
            [deck refreshAllBars];
            return;
        }

        // 3. Keyboard Shortcuts
        if (type == NSEventTypeKeyDown) {
            NSString *chars = [event.charactersIgnoringModifiers lowercaseString] ?: @"";
            unsigned short kc = event.keyCode;
            NSEventModifierFlags coreMods = mods & (NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl);

            if (coreMods == NSEventModifierFlagCommand) {
                // Cmd + '=' / '+' -> Zoom Page In
                if ([chars isEqualToString:@"="] || [chars isEqualToString:@"+"] || kc == 24 || kc == 69) {
                    [deck zoomActivePageByFactor:1.20 centeredAtWindowPoint:NSZeroPoint useCenter:YES];
                    return;
                }
                // Cmd + '-' / '_' -> Zoom Page Out
                if ([chars isEqualToString:@"-"] || [chars isEqualToString:@"_"] || kc == 27 || kc == 78) {
                    [deck zoomActivePageByFactor:(1.0 / 1.20) centeredAtWindowPoint:NSZeroPoint useCenter:YES];
                    return;
                }
                // Cmd + '0' -> Reset Page Zoom to 100%
                if ([chars isEqualToString:@"0"] || kc == 29 || kc == 82) {
                    [deck resetActivePageZoom];
                    return;
                }
            } else if (coreMods == (NSEventModifierFlagCommand | NSEventModifierFlagOption)) {
                // Cmd + Option + '+' / '-' / '0' -> Adjust Phone Window Display Scale
                if ([chars isEqualToString:@"="] || [chars isEqualToString:@"+"] || kc == 24 || kc == 69) {
                    [deck setWindowDisplayScale:(deck.displayScale + 0.15)];
                    return;
                }
                if ([chars isEqualToString:@"-"] || [chars isEqualToString:@"_"] || kc == 27 || kc == 78) {
                    [deck setWindowDisplayScale:(deck.displayScale - 0.15)];
                    return;
                }
                if ([chars isEqualToString:@"0"] || kc == 29 || kc == 82) {
                    [deck setWindowDisplayScale:1.0];
                    return;
                }
            }

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
            } else if ((mods & NSEventModifierFlagControl) && kc == 48 && deck.items.count > 1) {
                NSUInteger cur = [deck.items indexOfObjectIdenticalTo:deck.activeItem];
                if (cur != NSNotFound) {
                    BOOL rev = (mods & NSEventModifierFlagShift) != 0;
                    NSUInteger next = rev ? ((cur + deck.items.count - 1) % deck.items.count) : ((cur + 1) % deck.items.count);
                    [deck selectTabAtIndex:next];
                    return;
                }
            }
        }
    }
    ((void (*)(id, SEL, NSEvent *))gOrigSendEvent)(self, _cmd, event);
}

static NSRect CloakCoerceWindowFrame(NSWindow *win, NSRect proposed) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if (deck.switching || ![deck isManagedBrowserWindow:win]) {
        return proposed;
    }

    // User corner/edge live-resize: scale the phone window proportionally while keeping exact iPhone aspect ratio!
    if (win.inLiveResize && win == deck.activeItem.window && win.isVisible && deck.hasSharedFrame) {
        NSRect oldF = deck.sharedFrame;
        CGFloat chromeH = CloakWindowChromeHeight(win);
        CGFloat dw = fabs(proposed.size.width - oldF.size.width);
        CGFloat dh = fabs(proposed.size.height - oldF.size.height);
        CGFloat rawScale = (dw >= dh * 0.45)
            ? (proposed.size.width / gBaseWidth)
            : ((proposed.size.height - chromeH) / gBaseHeight);
        CGFloat s = [deck clampDisplayScale:rawScale forWindow:win];
        NSSize newSz = [deck windowFrameSizeForScale:s window:win];

        BOOL draggedLeftEdge = fabs(proposed.origin.x - oldF.origin.x) > 0.5;
        BOOL topEdgeFixed = fabs(NSMaxY(proposed) - NSMaxY(oldF)) < 1.5;
        CGFloat newX = draggedLeftEdge ? (NSMaxX(oldF) - newSz.width) : oldF.origin.x;
        CGFloat newY = topEdgeFixed ? (NSMaxY(oldF) - newSz.height) : oldF.origin.y;

        deck.displayScale = s;
        deck.sharedFrame = NSMakeRect(round(newX), round(newY), newSz.width, newSz.height);
        deck.hasSettledSize = YES;
        CloakPersistGeometry(deck.sharedFrame.origin, s);
        return deck.sharedFrame;
    }

    BOOL leftMouseDown = ([NSEvent pressedMouseButtons] & 1) != 0;
    if ((deck.userDragging || leftMouseDown) && win == deck.activeItem.window && win.isVisible && deck.hasSharedFrame) {
        deck.sharedFrame = NSMakeRect(proposed.origin.x, proposed.origin.y, deck.sharedFrame.size.width, deck.sharedFrame.size.height);
        return deck.sharedFrame;
    }

    if (!deck.hasSharedFrame) {
        CGFloat s = [deck clampDisplayScale:deck.displayScale forWindow:win];
        NSSize sz = [deck windowFrameSizeForScale:s window:win];
        deck.sharedFrame = NSMakeRect(proposed.origin.x, NSMaxY(proposed) - sz.height, sz.width, sz.height);
        deck.hasSharedFrame = YES;
        deck.hasSettledSize = YES;
        return deck.sharedFrame;
    }
    return deck.sharedFrame;
}

static void Swizzled_setFrameDisplay(NSWindow *self, SEL _cmd, NSRect frameRect, BOOL flag) {
    NSRect locked = CloakCoerceWindowFrame(self, frameRect);
    BOOL prev = gInProgrammaticFrameCall;
    gInProgrammaticFrameCall = YES;
    ((void (*)(id, SEL, NSRect, BOOL))gOrigSetFrameDisplay)(self, _cmd, locked, flag);
    [[CloakTabDeck shared] enforceWebViewLogicalBoundsForWindow:self];
    gInProgrammaticFrameCall = prev;
    if (self.inLiveResize) {
        [[CloakTabDeck shared] refreshAllBars];
    }
}

static void Swizzled_setFrameDisplayAnimate(NSWindow *self, SEL _cmd, NSRect frameRect, BOOL displayFlag, BOOL animateFlag) {
    (void)animateFlag;
    NSRect locked = CloakCoerceWindowFrame(self, frameRect);
    BOOL prev = gInProgrammaticFrameCall;
    gInProgrammaticFrameCall = YES;
    ((void (*)(id, SEL, NSRect, BOOL, BOOL))gOrigSetFrameDisplayAnimate)(self, _cmd, locked, displayFlag, NO);
    [[CloakTabDeck shared] enforceWebViewLogicalBoundsForWindow:self];
    gInProgrammaticFrameCall = prev;
}

static void Swizzled_setFrameOrigin(NSWindow *self, SEL _cmd, NSPoint point) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    BOOL leftMouseDown = ([NSEvent pressedMouseButtons] & 1) != 0;
    if (!deck.switching && !(deck.userDragging || leftMouseDown) && deck.hasSharedFrame && [deck isManagedBrowserWindow:self]) {
        point = deck.sharedFrame.origin;
    }
    BOOL prev = gInProgrammaticFrameCall;
    gInProgrammaticFrameCall = YES;
    ((void (*)(id, SEL, NSPoint))gOrigSetFrameOrigin)(self, _cmd, point);
    gInProgrammaticFrameCall = prev;
}

static void Swizzled_setFrameTopLeftPoint(NSWindow *self, SEL _cmd, NSPoint point) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    BOOL leftMouseDown = ([NSEvent pressedMouseButtons] & 1) != 0;
    if (!deck.switching && !(deck.userDragging || leftMouseDown) && deck.hasSharedFrame && [deck isManagedBrowserWindow:self]) {
        point = NSMakePoint(deck.sharedFrame.origin.x, NSMaxY(deck.sharedFrame));
    }
    BOOL prev = gInProgrammaticFrameCall;
    gInProgrammaticFrameCall = YES;
    ((void (*)(id, SEL, NSPoint))gOrigSetFrameTopLeft)(self, _cmd, point);
    gInProgrammaticFrameCall = prev;
}

static NSPoint Swizzled_cascadeTopLeftFromPoint(NSWindow *self, SEL _cmd, NSPoint topLeftPoint) {
    CloakTabDeck *deck = [CloakTabDeck shared];
    if ([deck isManagedBrowserWindow:self]) {
        if (deck.hasSharedFrame) {
            return NSMakePoint(deck.sharedFrame.origin.x, NSMaxY(deck.sharedFrame));
        }
        return topLeftPoint;
    }
    return ((NSPoint (*)(id, SEL, NSPoint))gOrigCascadeTopLeft)(self, _cmd, topLeftPoint);
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

    Method mFrameDisp = class_getInstanceMethod(winCls, @selector(setFrame:display:));
    if (mFrameDisp) gOrigSetFrameDisplay = method_setImplementation(mFrameDisp, (IMP)Swizzled_setFrameDisplay);

    Method mFrameAnim = class_getInstanceMethod(winCls, @selector(setFrame:display:animate:));
    if (mFrameAnim) gOrigSetFrameDisplayAnimate = method_setImplementation(mFrameAnim, (IMP)Swizzled_setFrameDisplayAnimate);

    Method mOrigin = class_getInstanceMethod(winCls, @selector(setFrameOrigin:));
    if (mOrigin) gOrigSetFrameOrigin = method_setImplementation(mOrigin, (IMP)Swizzled_setFrameOrigin);

    Method mTopLeft = class_getInstanceMethod(winCls, @selector(setFrameTopLeftPoint:));
    if (mTopLeft) gOrigSetFrameTopLeft = method_setImplementation(mTopLeft, (IMP)Swizzled_setFrameTopLeftPoint);

    Method mCascade = class_getInstanceMethod(winCls, @selector(cascadeTopLeftFromPoint:));
    if (mCascade) gOrigCascadeTopLeft = method_setImplementation(mCascade, (IMP)Swizzled_cascadeTopLeftFromPoint);
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
        const char *envOriginFile = getenv("CLOAK_ORIGIN_FILE");
        if (envOriginFile && envOriginFile[0]) {
            gOriginFilePath = [NSString stringWithUTF8String:envOriginFile];
        }
        const char *envTabsFile = getenv("CLOAK_TABS_FILE");
        if (envTabsFile && envTabsFile[0]) {
            gTabsFilePath = [NSString stringWithUTF8String:envTabsFile];
        }
        const char *envBaseW = getenv("CLOAK_BASE_WIDTH");
        if (envBaseW && envBaseW[0]) {
            double bw = atof(envBaseW);
            if (bw >= 240.0 && bw <= 1600.0) gBaseWidth = (CGFloat)bw;
        }
        const char *envBaseH = getenv("CLOAK_BASE_HEIGHT");
        if (envBaseH && envBaseH[0]) {
            double bh = atof(envBaseH);
            if (bh >= 360.0 && bh <= 2600.0) gBaseHeight = (CGFloat)bh;
        }
        const char *envScale = getenv("CLOAK_DISPLAY_SCALE");
        if (envScale && envScale[0]) {
            double sc = atof(envScale);
            if (sc >= 0.85 && sc <= 1.80) gInitialScaleEnv = (CGFloat)sc;
        }

        NSUserDefaults *ud = [NSUserDefaults standardUserDefaults];
        for (NSString *key in [[ud dictionaryRepresentation] allKeys]) {
            if ([key hasPrefix:@"NSWindow Frame "]) {
                [ud removeObjectForKey:key];
            }
        }
        gHostFavicons = [NSMutableDictionary dictionary];
        InstallCloakWebKitTabs();
    }
}
