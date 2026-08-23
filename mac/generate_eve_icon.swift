import AppKit
import Foundation

func makeColor(_ hex: Int, alpha: CGFloat = 1.0) -> NSColor {
    NSColor(
        calibratedRed: CGFloat((hex >> 16) & 0xff) / 255.0,
        green: CGFloat((hex >> 8) & 0xff) / 255.0,
        blue: CGFloat(hex & 0xff) / 255.0,
        alpha: alpha
    )
}

func circlePoint(center: CGPoint, radius: CGFloat, degrees: CGFloat) -> CGPoint {
    let radians = degrees * .pi / 180.0
    return CGPoint(
        x: center.x + cos(radians) * radius,
        y: center.y + sin(radians) * radius
    )
}

func drawArc(
    center: CGPoint,
    radius: CGFloat,
    startAngle: CGFloat,
    endAngle: CGFloat,
    lineWidth: CGFloat,
    color: NSColor
) {
    let path = NSBezierPath()
    path.appendArc(withCenter: center, radius: radius, startAngle: startAngle, endAngle: endAngle)
    path.lineWidth = lineWidth
    path.lineCapStyle = .round
    color.setStroke()
    path.stroke()
}

func drawDot(center: CGPoint, radius: CGFloat, color: NSColor, glow: NSColor? = nil) {
    if let glow {
        let glowPath = NSBezierPath(ovalIn: CGRect(
            x: center.x - radius * 1.7,
            y: center.y - radius * 1.7,
            width: radius * 3.4,
            height: radius * 3.4
        ))
        glow.setFill()
        glowPath.fill()
    }
    let path = NSBezierPath(ovalIn: CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
    color.setFill()
    path.fill()
}

func drawSpark(center: CGPoint, size: CGFloat, color: NSColor) {
    let vertical = NSBezierPath()
    vertical.move(to: CGPoint(x: center.x, y: center.y - size))
    vertical.line(to: CGPoint(x: center.x, y: center.y + size))
    vertical.lineWidth = size * 0.28
    vertical.lineCapStyle = .round
    color.setStroke()
    vertical.stroke()

    let horizontal = NSBezierPath()
    horizontal.move(to: CGPoint(x: center.x - size, y: center.y))
    horizontal.line(to: CGPoint(x: center.x + size, y: center.y))
    horizontal.lineWidth = size * 0.28
    horizontal.lineCapStyle = .round
    color.setStroke()
    horizontal.stroke()
}

func drawRibbon(points: [CGPoint], lineWidth: CGFloat, color: NSColor) {
    guard points.count >= 4 else { return }
    let path = NSBezierPath()
    path.move(to: points[0])
    path.curve(to: points[3], controlPoint1: points[1], controlPoint2: points[2])
    path.lineWidth = lineWidth
    path.lineCapStyle = .round
    path.lineJoinStyle = .round
    color.setStroke()
    path.stroke()
}

autoreleasepool {
    let outputPath = CommandLine.arguments.dropFirst().first ?? "eve-icon.png"
    let outputURL = URL(fileURLWithPath: outputPath)
    let canvasSize: CGFloat = 1024
    let image = NSImage(size: NSSize(width: canvasSize, height: canvasSize))

    image.lockFocus()
    guard let context = NSGraphicsContext.current?.cgContext else {
        fputs("Could not create graphics context.\n", stderr)
        exit(1)
    }

    context.interpolationQuality = .high
    context.setShouldAntialias(true)
    context.setAllowsAntialiasing(true)

    let outerRect = CGRect(x: 36, y: 36, width: canvasSize - 72, height: canvasSize - 72)
    let outerPath = NSBezierPath(roundedRect: outerRect, xRadius: 220, yRadius: 220)
    outerPath.addClip()

    makeColor(0xF8ECDE).setFill()
    outerPath.fill()

    let backgroundGradient = NSGradient(colors: [
        makeColor(0xFFF4E7),
        makeColor(0xF4C79D),
        makeColor(0xDE8D64),
        makeColor(0x2D6678),
    ])!
    backgroundGradient.draw(in: outerPath, angle: -32)

    let amberGlow = NSGradient(starting: makeColor(0xFFD792, alpha: 0.72), ending: makeColor(0xFFD792, alpha: 0.0))!
    amberGlow.draw(
        fromCenter: CGPoint(x: 246, y: 772),
        radius: 20,
        toCenter: CGPoint(x: 246, y: 772),
        radius: 410,
        options: []
    )

    let tealGlow = NSGradient(starting: makeColor(0x83CED8, alpha: 0.60), ending: makeColor(0x83CED8, alpha: 0.0))!
    tealGlow.draw(
        fromCenter: CGPoint(x: 790, y: 280),
        radius: 10,
        toCenter: CGPoint(x: 790, y: 280),
        radius: 360,
        options: []
    )

    let hazePath = NSBezierPath(rect: CGRect(x: 0, y: 0, width: canvasSize, height: canvasSize))
    let hazeGradient = NSGradient(colors: [
        makeColor(0xFFFFFF, alpha: 0.24),
        makeColor(0xFFFFFF, alpha: 0.0),
    ])!
    hazeGradient.draw(in: hazePath, angle: 90)

    let center = CGPoint(x: canvasSize / 2, y: canvasSize / 2)
    let ringColor = makeColor(0xFFF9F2, alpha: 0.18)
    [298.0, 354.0, 420.0].forEach { radius in
        let ring = NSBezierPath(ovalIn: CGRect(
            x: center.x - radius,
            y: center.y - radius,
            width: radius * 2,
            height: radius * 2
        ))
        ring.lineWidth = 9
        ringColor.setStroke()
        ring.stroke()
    }

    drawArc(center: center, radius: 286, startAngle: 150, endAngle: 325, lineWidth: 44, color: makeColor(0xF9F2EA, alpha: 0.56))
    drawArc(center: center, radius: 236, startAngle: 203, endAngle: 18, lineWidth: 30, color: makeColor(0x2E677A, alpha: 0.88))
    drawArc(center: center, radius: 196, startAngle: 14, endAngle: 206, lineWidth: 26, color: makeColor(0xC65B38, alpha: 0.84))

    drawDot(
        center: circlePoint(center: center, radius: 286, degrees: 325),
        radius: 23,
        color: makeColor(0xFFF7EF),
        glow: makeColor(0xFFF7EF, alpha: 0.30)
    )
    drawDot(
        center: circlePoint(center: center, radius: 236, degrees: 18),
        radius: 18,
        color: makeColor(0x2E677A),
        glow: makeColor(0x2E677A, alpha: 0.18)
    )
    drawDot(
        center: circlePoint(center: center, radius: 196, degrees: 206),
        radius: 16,
        color: makeColor(0xC65B38),
        glow: makeColor(0xC65B38, alpha: 0.16)
    )

    let orbRect = CGRect(x: center.x - 176, y: center.y - 176, width: 352, height: 352)
    let orbPath = NSBezierPath(ovalIn: orbRect)

    NSGraphicsContext.saveGraphicsState()
    let orbShadow = NSShadow()
    orbShadow.shadowBlurRadius = 52
    orbShadow.shadowOffset = NSSize(width: 0, height: -10)
    orbShadow.shadowColor = makeColor(0x71331E, alpha: 0.28)
    orbShadow.set()
    makeColor(0xFFF7EF, alpha: 0.96).setFill()
    orbPath.fill()
    NSGraphicsContext.restoreGraphicsState()

    let orbGradient = NSGradient(colors: [
        makeColor(0xFFFDF8),
        makeColor(0xF8E5D2),
        makeColor(0xEEDACB),
    ])!
    orbGradient.draw(in: orbPath, relativeCenterPosition: NSPoint(x: -0.18, y: 0.34))

    let innerGlow = NSGradient(starting: makeColor(0x8FD1D5, alpha: 0.22), ending: makeColor(0x8FD1D5, alpha: 0.0))!
    innerGlow.draw(
        fromCenter: CGPoint(x: center.x + 38, y: center.y + 26),
        radius: 8,
        toCenter: CGPoint(x: center.x + 38, y: center.y + 26),
        radius: 154,
        options: []
    )

    let highlightPath = NSBezierPath(ovalIn: CGRect(x: center.x - 118, y: center.y + 12, width: 154, height: 88))
    makeColor(0xFFFFFF, alpha: 0.28).setFill()
    highlightPath.fill()

    drawRibbon(
        points: [
            CGPoint(x: center.x - 90, y: center.y + 74),
            CGPoint(x: center.x - 10, y: center.y + 132),
            CGPoint(x: center.x + 62, y: center.y + 84),
            CGPoint(x: center.x + 72, y: center.y + 14),
        ],
        lineWidth: 28,
        color: makeColor(0x2E677A, alpha: 0.95)
    )

    drawRibbon(
        points: [
            CGPoint(x: center.x - 84, y: center.y - 8),
            CGPoint(x: center.x - 22, y: center.y + 38),
            CGPoint(x: center.x + 44, y: center.y + 6),
            CGPoint(x: center.x + 56, y: center.y - 46),
        ],
        lineWidth: 25,
        color: makeColor(0xC65B38, alpha: 0.92)
    )

    drawRibbon(
        points: [
            CGPoint(x: center.x - 60, y: center.y - 94),
            CGPoint(x: center.x + 6, y: center.y - 122),
            CGPoint(x: center.x + 58, y: center.y - 82),
            CGPoint(x: center.x + 86, y: center.y - 24),
        ],
        lineWidth: 22,
        color: makeColor(0x72843B, alpha: 0.84)
    )

    drawSpark(center: CGPoint(x: center.x + 146, y: center.y + 146), size: 34, color: makeColor(0xFFF8F0, alpha: 0.92))

    let rimPath = NSBezierPath(roundedRect: outerRect.insetBy(dx: 4, dy: 4), xRadius: 214, yRadius: 214)
    rimPath.lineWidth = 8
    makeColor(0xFFF8F0, alpha: 0.26).setStroke()
    rimPath.stroke()

    image.unlockFocus()

    guard
        let tiffData = image.tiffRepresentation,
        let bitmap = NSBitmapImageRep(data: tiffData),
        let pngData = bitmap.representation(using: .png, properties: [:])
    else {
        fputs("Could not create PNG data.\n", stderr)
        exit(1)
    }

    do {
        try FileManager.default.createDirectory(
            at: outputURL.deletingLastPathComponent(),
            withIntermediateDirectories: true,
            attributes: nil
        )
        try pngData.write(to: outputURL)
    } catch {
        fputs("Could not write icon: \(error)\n", stderr)
        exit(1)
    }
}
