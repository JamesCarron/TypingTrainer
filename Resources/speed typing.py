import pygame
from pygame.locals import *
import sys
import time

window_width = 750
window_height = 500

reading_line = 0
text_file_location = 'Texts/artofwar.txt'


class Image:
    def __init__(self, unique_identifier, location, width, height):
        self.id = unique_identifier
        self.loc = location
        self.w = width
        self.h = height
        self.pygame = pygame.transform.scale(pygame.image.load(self.loc), (self.w, self.h))

    def pygame_load(self):
        img = pygame.image.load(self.loc)
        return pygame.transform.scale(img, (self.w, self.h))


def get_text(file_location):
    return [line.strip() for line in open(file_location).readlines()]


class Game:

    def __init__(self):
        self.w = window_width
        self.h = window_height
        self.active = False
        self.input_text = ''
        self.sentence = ''
        self.time_start = 0
        self.results_str = 'Time:NA Accuracy:NA % Wpm:NA'
        self.end = False
        self.HEAD_C = (255, 213, 102)
        self.TEXT_C = (240, 240, 240)
        self.RESULT_C = (255, 70, 70)
        self.running = True
        self.state = 'INIT'
        print(self.state)

        pygame.init()

        images = [Image(unique_identifier='open', location='Images/type-speed-open.png', width=self.w, height=self.h),
                  Image(unique_identifier='bg', location='Images/background.jpg', width=500, height=750),
                  Image(unique_identifier='icon', location='Images/icon.png', width=150, height=150)]

        self.images = {img.id: img for img in images}

        self.screen = pygame.display.set_mode((self.w, self.h))
        pygame.display.set_caption('Type Speed test')

    def draw_text(self, screen, msg, y, fsize, color):
        font = pygame.font.Font(None, fsize)
        text = font.render(msg, 1, color)
        text_rect = text.get_rect(center=(self.w / 2, y))
        screen.blit(text, text_rect)
        pygame.display.update()

    def show_results(self, screen):
        if not self.end:  # if the game is finished
            # Calculate time
            total_time = time.time() - self.time_start

            # Compare user input to given sentence character by character
            matches = [guess == ans for guess, ans in zip(self.input_text, self.sentence)]
            accuracy = (sum(matches) / len(self.sentence))
            if accuracy < 1:
                print(f"Diff: {str([int(char) for char in matches])}")

            # Calculate words per minute
            wpm = len(self.input_text) * 60 / (5 * total_time)
            self.results_str = f"Time: {total_time:.2f} secs   Accuracy: {accuracy:.2%} %   Wpm: {wpm:.2f}"

            # draw icon image
            screen.blit(self.images['icon'].pygame, (self.w / 2 - 75, self.h - 140))
            self.draw_text(screen, "Reset", self.h - 70, 26, (100, 100, 100))
            pygame.display.update()

    def run(self):
        self.reset_game()

        while self.state != 'QUIT':
            clock = pygame.time.Clock()
            self.screen.fill((0, 0, 0), (50, 250, 650, 50))
            pygame.draw.rect(self.screen, self.HEAD_C, (50, 250, 650, 50), 2)
            # update the text of user input
            self.draw_text(self.screen, self.input_text, 274, 26, (250, 250, 250))
            if self.state == 'READY':
                self.draw_text(self.screen, 'PRESS ENTER TO START', 400, 26, (250, 250, 250))

            pygame.display.update()

            # take user input
            for event in pygame.event.get():
                if event.type == QUIT:
                    self.state = 'QUIT'
                    print(self.state)
                    break

                elif self.state == 'GAME':
                    if event.type == pygame.MOUSEBUTTONUP:
                        x, y = pygame.mouse.get_pos()

                    elif event.type == pygame.KEYDOWN:
                        if self.state == 'GAME':
                            if event.key == pygame.K_RETURN:
                                print(f"User: '{self.input_text}'")
                                self.show_results(self.screen)
                                print(self.results_str)
                                self.draw_text(self.screen, self.results_str, 350, 28, self.RESULT_C)
                                if self.input_text == self.sentence:
                                    global reading_line
                                    reading_line += 1
                                self.state = 'GAMEOVER'
                                print(self.state)

                            elif event.key == pygame.K_BACKSPACE:
                                self.input_text = self.input_text[:-1]

                            # normal char to be displayed to screen.
                            else:
                                self.input_text += event.unicode

                elif self.state == 'GAMEOVER':
                    if event.type == pygame.MOUSEBUTTONUP:
                        x, y = pygame.mouse.get_pos()
                        if 310 <= x <= 510 and y >= 390:
                            self.state = 'RESET'
                            print(self.state)

                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_RETURN:
                            self.time_start = time.time()
                            self.state = 'RESET'
                            print(self.state)

                elif self.state == 'READY':
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_RETURN:
                            self.time_start = time.time()
                            self.state = 'GAME'
                            print(self.state)
                            pygame.draw.rect(self.screen, self.HEAD_C, (50, 250, 650, 50), 2)

                elif self.state == 'RESET':
                    self.reset_game()

        clock.tick(60)

    def reset_game(self):
        self.screen.blit(self.images['open'].pygame, (0, 0))
        pygame.display.update()
        time.sleep(1)

        self.input_text = ''
        self.sentence = get_sentence(text_file_location, reading_line)
        print(f"Text: '{self.sentence}'")

        # drawing heading
        self.screen.fill((0, 0, 0))
        self.screen.blit(self.images['bg'].pygame, (0, 0))
        msg = "Typing Speed Test"
        self.draw_text(self.screen, msg, 80, 80, self.HEAD_C)
        # draw the rectangle for input box
        pygame.draw.rect(self.screen, (255, 192, 25), (50, 250, 650, 50), 2)

        # draw the sentence string
        self.draw_text(self.screen, self.sentence, 200, 28, self.TEXT_C)

        pygame.display.update()
        self.state = 'READY'
        print(self.state)


Game().run()
