import {
  Box,
  Text,
  VStack,
  Badge,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText
} from '@chakra-ui/react'

export default function StockCard({ name, data }) {
  const isPositive = data.change >= 0
  const changeColor = isPositive ? 'green.400' : 'red.400'
  
  return (
    <Box
      bg="gray.800"
      border="1px solid"
      borderColor="gray.700" 
      borderRadius="md"
      boxShadow="lg"
      p={5}
      mb={5}
    >
      <VStack spacing={3} align="start">
        <Text fontSize="lg" fontWeight="bold" color="white">{name}</Text>
        <Badge colorScheme="blue">{data.symbol}</Badge>

        <Stat>
          <StatLabel>Current Price</StatLabel>
          <StatNumber color="white">₹{data.price !== 'N/A' ? data.price.toLocaleString() : 'N/A'}</StatNumber>
          <StatHelpText color={changeColor}>
            {isPositive ? '+' : ''}₹{data.change} ({isPositive ? '+' : ''}{data.changePercent}%)
          </StatHelpText>
        </Stat>
      </VStack>
    </Box>
  )
}
