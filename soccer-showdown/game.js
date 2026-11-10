(() => {
    "use strict";

    const canvas = document.getElementById("pitch");
    const context = canvas.getContext("2d");
    const playerScoreElement = document.getElementById("player-score");
    const botScoreElement = document.getElementById("bot-score");
    const statusElement = document.getElementById("game-status");
    const startButton = document.getElementById("start-button");
    const levelSelect = document.getElementById("level-select");
    const powerTrack = document.getElementById("power-track");
    const powerFill = document.getElementById("power-fill");
    const powerValue = document.getElementById("power-value");

    const width = canvas.width;
    const height = canvas.height;
    const field = { left: 52, right: width - 52, top: 38, bottom: height - 38 };
    const goalTop = height / 2 - 68;
    const goalBottom = height / 2 + 68;
    const playerRadius = 21;
    const ballRadius = 10;
    const maxChargeMs = 1200;
    const keys = new Set();
    const player = { x: width * 0.28, y: height / 2, dx: 1, dy: 0 };
    const bot = { x: width * 0.72, y: height / 2, dx: -1, dy: 0 };
    const ball = { x: width / 2, y: height / 2, vx: 0, vy: 0 };
    const winningScore = 5;
    const levels = [
        { speed: 1.8, reaction: 0.5, stealChance: 0.15 },
        { speed: 2.2, reaction: 0.64, stealChance: 0.3 },
        { speed: 2.7, reaction: 0.78, stealChance: 0.45 },
        { speed: 3.2, reaction: 0.9, stealChance: 0.65 },
        { speed: 4.6, reaction: 1, stealChance: 0.82 }
    ];
    let playerScore = 0;
    let botScore = 0;
    let level = 1;
    let playing = false;
    let finished = false;
    let playerKickCooldown = 0;
    let botKickCooldown = 0;
    let playerStealCooldown = 0;
    let botStealCooldown = 0;
    let chargingShot = false;
    let dribbling = false;
    let chargeStartedAt = 0;
    let shotCharge = 0;
    let previousTime = 0;

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function updateScore() {
        playerScoreElement.textContent = String(playerScore);
        botScoreElement.textContent = String(botScore);
    }

    function resetPositions() {
        player.x = width * 0.28;
        player.y = height / 2;
        player.dx = 1;
        player.dy = 0;
        bot.x = width * 0.72;
        bot.y = height / 2;
        bot.dx = -1;
        bot.dy = 0;
        ball.x = width / 2;
        ball.y = height / 2;
        ball.vx = 0;
        ball.vy = 0;
        playerKickCooldown = 0;
        dribbling = false;
        keys.delete("d");
        botKickCooldown = 0;
        playerStealCooldown = 0;
        botStealCooldown = 0;
        chargingShot = false;
        chargeStartedAt = 0;
        shotCharge = 0;
        updatePowerMeter();
    }

    function startMatch() {
        if (finished) {
            playerScore = 0;
            botScore = 0;
            updateScore();
            finished = false;
        }
        resetPositions();
        playing = true;
        startButton.hidden = true;
        statusElement.textContent = `Level ${level}: move with arrows. Hold D near the ball to dribble, hold Space to charge a shot, and press Alt near the bot to steal.`;
        canvas.focus();
    }

    function endPoint(scorer) {
        playing = false;
        if (scorer === "player") {
            playerScore += 1;
        } else {
            botScore += 1;
        }
        updateScore();

        if (playerScore >= winningScore || botScore >= winningScore) {
            finished = true;
            statusElement.textContent = playerScore > botScore ? "You win the match!" : "The bot wins this time.";
            startButton.textContent = "Play again";
        } else {
            statusElement.textContent = scorer === "player"
                ? "Goal! You're in the lead. Get ready for kickoff."
                : "The bot scored. Get ready for kickoff.";
            startButton.textContent = "Next kickoff";
        }
        startButton.hidden = false;
        resetPositions();
    }

    function moveEntity(entity, dx, dy, speed, step) {
        const magnitude = Math.hypot(dx, dy);
        if (magnitude > 0) {
            entity.dx = dx / magnitude;
            entity.dy = dy / magnitude;
            entity.x += entity.dx * speed * step;
            entity.y += entity.dy * speed * step;
        }
        entity.x = clamp(entity.x, field.left + playerRadius, field.right - playerRadius);
        entity.y = clamp(entity.y, field.top + playerRadius, field.bottom - playerRadius);
    }

    function kick(entity, targetX, targetY, power, directionX, directionY) {
        const distance = Math.hypot(ball.x - entity.x, ball.y - entity.y);
        if (distance > playerRadius + ballRadius + 20) {
            return false;
        }
        const dx = directionX === undefined ? targetX - ball.x : directionX;
        const dy = directionY === undefined ? targetY - ball.y : directionY;
        const magnitude = Math.hypot(dx, dy) || 1;
        ball.vx = (dx / magnitude) * power;
        ball.vy = (dy / magnitude) * power;
        return true;
    }

    function kickTowardBall(entity, power) {
        const dx = ball.x - entity.x;
        const dy = ball.y - entity.y;
        const distance = Math.hypot(dx, dy);
        const directionX = distance > 0 ? dx : entity.dx;
        const directionY = distance > 0 ? dy : entity.dy;
        return kick(entity, 0, 0, power, directionX, directionY);
    }

    function updatePowerMeter() {
        const percent = Math.round(shotCharge * 100);
        powerFill.style.width = `${percent}%`;
        powerValue.textContent = `${percent}%`;
        powerTrack.setAttribute("aria-valuenow", String(percent));
    }

    function releaseShot() {
        if (!chargingShot) {
            return;
        }
        chargingShot = false;
        const charge = clamp((Date.now() - chargeStartedAt) / maxChargeMs, 0, 1);
        chargeStartedAt = 0;
        shotCharge = 0;
        updatePowerMeter();

        if (playing && playerKickCooldown <= 0) {
            const power = 4.8 + charge * 5.2;
            if (kickTowardBall(player, power)) {
                playerKickCooldown = 18;
                statusElement.textContent = `Shot! Power ${Math.round(charge * 100)}%.`;
            } else {
                statusElement.textContent = "Get close to the ball before shooting.";
            }
        }
    }

    function attemptPlayerSteal() {
        if (!playing || playerStealCooldown > 0) {
            return;
        }

        const playerBotDistance = Math.hypot(player.x - bot.x, player.y - bot.y);
        const ballBotDistance = Math.hypot(ball.x - bot.x, ball.y - bot.y);
        if (
            playerBotDistance <= playerRadius * 2 + 12 &&
            ballBotDistance <= playerRadius + ballRadius + 24
        ) {
            const stolen = kickTowardBall(player, 7.4);
            if (stolen) {
                playerStealCooldown = 36;
                statusElement.textContent = "Steal! Take the ball toward the bot's goal.";
                return;
            }
        }

        playerStealCooldown = 12;
        statusElement.textContent = "Get close to the bot and the ball to steal.";
    }

    function startPlayerDribbling() {
        if (!playing) {
            return;
        }

        const distance = Math.hypot(ball.x - player.x, ball.y - player.y);
        if (distance > playerRadius + ballRadius + 20) {
            statusElement.textContent = "Move close to the ball while holding D to dribble.";
        }
        dribbling = true;
    }

    function tryBotSteal(difficulty) {
        const playerDistance = Math.hypot(bot.x - player.x, bot.y - player.y);
        const ballDistance = Math.hypot(ball.x - player.x, ball.y - player.y);
        if (
            botStealCooldown <= 0 &&
            playerDistance <= playerRadius * 2 + 9 &&
            ballDistance <= playerRadius + ballRadius + 18 &&
            Math.random() < difficulty.stealChance
        ) {
            const stolen = kick(bot, field.left - 80, bot.y + (height / 2 - bot.y) * 0.25, 6.8);
            if (stolen) {
                dribbling = false;
                botStealCooldown = 42;
                statusElement.textContent = "The bot stole the ball! Get it back.";
                return true;
            }
        }
        return false;
    }

    function update(delta) {
        const step = Math.min(delta / 16.67, 2);
        if (!playing) {
            return;
        }

        playerKickCooldown = Math.max(0, playerKickCooldown - step);
        botKickCooldown = Math.max(0, botKickCooldown - step);
        playerStealCooldown = Math.max(0, playerStealCooldown - step);
        botStealCooldown = Math.max(0, botStealCooldown - step);
        let moveX = 0;
        let moveY = 0;
        if (keys.has("ArrowLeft") || keys.has("a")) moveX -= 1;
        if (keys.has("ArrowRight")) moveX += 1;
        if (keys.has("ArrowUp") || keys.has("w")) moveY -= 1;
        if (keys.has("ArrowDown") || keys.has("s")) moveY += 1;
        moveEntity(player, moveX, moveY, 4.3, step);

        const difficulty = levels[level - 1];
        const ballOnBotSide = ball.x > width * 0.53;
        const playerThreatening = player.x > width * 0.64;
        const botTargetX = ballOnBotSide || playerThreatening
            ? clamp(ball.x + 34, width * 0.55, field.right - playerRadius)
            : field.right - 118;
        const botTargetY = clamp(
            ball.y + (height / 2 - ball.y) * (1 - difficulty.reaction),
            field.top + playerRadius,
            field.bottom - playerRadius
        );
        const botDX = botTargetX - bot.x;
        const botDY = botTargetY - bot.y;
        if (Math.hypot(botDX, botDY) > playerRadius + 4) {
            moveEntity(bot, botDX, botDY, difficulty.speed, step);
        }

        if (botKickCooldown <= 0 && Math.hypot(ball.x - bot.x, ball.y - bot.y) < playerRadius + ballRadius + 18) {
            if (tryBotSteal(difficulty)) {
                botKickCooldown = 18;
            } else if (ball.x > width / 2) {
                if (kick(bot, field.left - 10, height / 2 + (Math.random() - 0.5) * (120 - level * 14), 5.8 + level * 0.18)) {
                    botKickCooldown = 28;
                }
            }
        }

        if (dribbling && !chargingShot) {
            const distance = Math.hypot(ball.x - player.x, ball.y - player.y);
            if (distance <= playerRadius + ballRadius + 20) {
                const ballOffset = playerRadius + ballRadius - 2;
                ball.x = player.x + player.dx * ballOffset;
                ball.y = player.y + player.dy * ballOffset;
                ball.vx = 0;
                ball.vy = 0;
            }
        }

        if (chargingShot) {
            shotCharge = clamp((Date.now() - chargeStartedAt) / maxChargeMs, 0, 1);
            updatePowerMeter();
        }

        ball.x += ball.vx * step;
        ball.y += ball.vy * step;
        const friction = Math.pow(0.985, step);
        ball.vx *= friction;
        ball.vy *= friction;

        if (ball.y - ballRadius < field.top || ball.y + ballRadius > field.bottom) {
            ball.y = clamp(ball.y, field.top + ballRadius, field.bottom - ballRadius);
            ball.vy *= -0.78;
        }

        if (ball.x - ballRadius < field.left && (ball.y < goalTop || ball.y > goalBottom)) {
            ball.x = field.left + ballRadius;
            ball.vx = Math.abs(ball.vx) * 0.78;
        } else if (ball.x + ballRadius > field.right && (ball.y < goalTop || ball.y > goalBottom)) {
            ball.x = field.right - ballRadius;
            ball.vx = -Math.abs(ball.vx) * 0.78;
        }

        if (ball.x < field.left - 18 && ball.y > goalTop && ball.y < goalBottom) {
            endPoint("bot");
        } else if (ball.x > field.right + 18 && ball.y > goalTop && ball.y < goalBottom) {
            endPoint("player");
        }

        if (Math.hypot(ball.vx, ball.vy) < 0.06) {
            ball.vx = 0;
            ball.vy = 0;
        }
    }

    function drawField() {
        context.clearRect(0, 0, width, height);
        context.fillStyle = "#176b4e";
        context.fillRect(0, 0, width, height);
        const stripeWidth = (field.right - field.left) / 8;
        for (let i = 0; i < 8; i += 1) {
            if (i % 2 === 0) {
                context.fillStyle = "rgba(255,255,255,0.035)";
                context.fillRect(field.left + i * stripeWidth, field.top, stripeWidth, field.bottom - field.top);
            }
        }

        context.strokeStyle = "rgba(245, 250, 239, 0.82)";
        context.lineWidth = 3;
        context.strokeRect(field.left, field.top, field.right - field.left, field.bottom - field.top);
        context.beginPath();
        context.moveTo(width / 2, field.top);
        context.lineTo(width / 2, field.bottom);
        context.stroke();
        context.beginPath();
        context.arc(width / 2, height / 2, 70, 0, Math.PI * 2);
        context.stroke();

        context.strokeStyle = "#f4f4e7";
        context.lineWidth = 4;
        context.strokeRect(field.left - 22, goalTop, 22, goalBottom - goalTop);
        context.strokeRect(field.right, goalTop, 22, goalBottom - goalTop);
        context.fillStyle = "rgba(255,255,255,0.08)";
        context.fillRect(field.left - 22, goalTop, 22, goalBottom - goalTop);
        context.fillRect(field.right, goalTop, 22, goalBottom - goalTop);

        drawPlayer(bot, "#ff8068", "BOT");
        drawPlayer(player, "#d3f36b", "YOU");
        context.beginPath();
        context.arc(ball.x, ball.y, ballRadius, 0, Math.PI * 2);
        context.fillStyle = "#fffdf2";
        context.fill();
        context.strokeStyle = "#253629";
        context.lineWidth = 2;
        context.stroke();
        context.beginPath();
        context.arc(ball.x, ball.y, 3, 0, Math.PI * 2);
        context.fillStyle = "#243229";
        context.fill();
    }

    function drawPlayer(entity, color, label) {
        context.beginPath();
        context.arc(entity.x, entity.y, playerRadius, 0, Math.PI * 2);
        context.fillStyle = color;
        context.fill();
        context.strokeStyle = "rgba(20, 38, 29, 0.6)";
        context.lineWidth = 3;
        context.stroke();
        context.fillStyle = "#17241b";
        context.font = "bold 9px Arial";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(label, entity.x, entity.y);
    }

    function frame(time) {
        const delta = previousTime === 0 ? 16.67 : time - previousTime;
        previousTime = time;
        update(delta);
        drawField();
        window.requestAnimationFrame(frame);
    }

    window.addEventListener("keydown", (event) => {
        const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
        if (event.target === levelSelect) {
            return;
        }
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " ", "Alt"].includes(key)) {
            event.preventDefault();
        }
        if (key === "Alt" && !event.repeat) {
            dribbling = false;
            attemptPlayerSteal();
        }
        if (key === "d") {
            if (!event.repeat) {
                startPlayerDribbling();
            }
            keys.add(key);
            return;
        }
        if (key === " ") {
            if (!playing && !finished) {
                startMatch();
            } else if (playing && !event.repeat && playerKickCooldown <= 0) {
                dribbling = false;
                chargingShot = true;
                chargeStartedAt = Date.now();
                shotCharge = 0;
                updatePowerMeter();
            }
            return;
        }
        keys.add(key);
    });
    window.addEventListener("keyup", (event) => {
        const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
        keys.delete(key);
        if (key === " ") {
            releaseShot();
        }
        if (key === "d") {
            dribbling = false;
        }
    });
    window.addEventListener("blur", () => {
        keys.clear();
        dribbling = false;
        releaseShot();
    });
    startButton.addEventListener("click", startMatch);
    levelSelect.addEventListener("change", () => {
        level = Number(levelSelect.value);
        if (!Number.isInteger(level) || level < 1 || level > levels.length) {
            throw new RangeError("Select a bot level from 1 to 5.");
        }
        if (!playing) {
            statusElement.textContent = `Level ${level} selected. Start the match when you're ready.`;
        }
    });

    drawField();
    window.requestAnimationFrame(frame);
})();
