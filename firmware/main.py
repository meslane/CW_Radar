import machine

def modify_word(word: int, bits: tuple[int, int], data: int):
    '''
    Modify specified bits in a 16 bit word
    
    word: 16 bit word to modify
    bits: bits in the word to modify, in the range [low, high] inclusive
    data: new data to insert into the provided bits, note bits outside the range will be ignored
    
    Returns: word with selected bits modified
    '''

    for i in range(bits[0], bits[1] + 1):
        word &= 0xFFFF & ~(0x1 << i)
        word |= ((data >> (i - bits[0])) & 0x0001) << i
        
    return word

class SPI_Device:
    def __init__(self, spi: machine.SPI, cs: machine.Pin):
        self.spi = spi
        self.cs = cs
        
        self.cs.value(1) #set CS high to deselect chip by default
        
    def spi_write_byte(self, data: int):
        byte = struct.pack(">B", data)
        self.spi.write(byte)

class LMX259x(SPI_Device):
    def __init__(self, spi: machine.SPI, cs:machine.Pin):
        super().__init__()
    
    def read(self, addr: int):
        '''
        Read a 16 bit word from the selected device address
        
        addr: device register to read from
        
        Returns: 16 bit word from selected address
        '''
        a_byte = (addr & 0x7F) | 0x80 #first byte must be high for serial read
        
        self.cs.value(0)
        self.spi_write_byte(a_byte)
        data = self.spi.read(2) #LMX registers are 16 bits
        self.cs.value(1)
        
        return int.from_bytes(data, "big")
    
    def write(self, addr: int, data: int):
        '''
        Write a 16 bit word to the selected device address
        
        addr: device register address to write
        data: 16 bit word to write to address
        '''
        a_byte = addr & 0x7F #first byte must be low for serial write
        
        #pack 16 bit word into two bytes
        d1_byte = (data >> 8) & 0xFF
        d2_byte = data & 0xFF
        
        self.cs.value(0)
        self.spi_write_byte(a_byte)
        self.spi_write_byte(d1_byte)
        self.spi_write_byte(d2_byte)
        self.cs.value(1)
        
    def modify(self, addr: int, bits: tuple[int, int], data: int):
        '''
        Write and modify bits within the selected range
        
        addr: Address to poke
        bits: Range of bits to modify in the format [low, high] inclusive
        data: New value for the selected bits. Out of range bits will be ignored.
        '''

        reg = self.read(addr)
        new_reg = modify_word(reg, bits, data)
        
        self.write(addr, new_reg)
        
    def reset(self):
        '''
        Reset device to default values by asserting RESET bit in R0
        '''
        self.modify(0x00, [1,1], 1)

def main():
    print(bin(modify_word(0xFFFF, (4, 7), 0b0101)))

if __name__ == "__main__":
    main()